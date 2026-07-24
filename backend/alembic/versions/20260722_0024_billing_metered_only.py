"""billing: purge estimates — metered Azure only

Removes Twilio/Pipecat/infra estimate catalog + usage.
Drops reconstructed embed backfill (not live Azure receipts).
Keeps sandbox chat usage_events (real token_count from Azure).
Rebuilds billing_usage_daily + invoices from remaining events.

Revision ID: 20260722_0024
Revises: 20260722_0023
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0024"
down_revision: Union[str, Sequence[str], None] = "20260722_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESTIMATE_IDS = (
    "tel_twilio",
    "wa_twilio",
    "pc_orch",
    "lake_ingest",
    "infra_flat",
    "llm_gpt4o",
    "svc-voice-minutes",
    "svc-rag-query",
)

METERED_IDS = ("llm_chat", "llm_embed", "stt_az", "tts_az")


def upgrade() -> None:
    conn = op.get_bind()

    # Drop estimate / obsolete usage + events
    if not seed_demo_enabled():
        return

    conn.execute(
        sa.text(
            """
            DELETE FROM usage_events
            WHERE service_id IN :ids
               OR coalesce(meta->>'backfill', '') = 'kb_chunks.tokens'
            """
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(ESTIMATE_IDS)},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM invoice_line_items
            WHERE service_id IN :ids
            """
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(ESTIMATE_IDS)},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM billing_usage_daily
            WHERE service_id IN :ids
               OR service_id = 'llm_embed'
            """
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(ESTIMATE_IDS)},
    )

    # Rebuild daily facts purely from remaining usage_events
    conn.execute(sa.text("DELETE FROM billing_usage_daily"))
    conn.execute(
        sa.text(
            """
            INSERT INTO billing_usage_daily (
              id, service_id, tenant_id, environment, usage_date, units, cost_inr
            )
            SELECT
              'bu-' || service_id || '-' || tenant_id || '-' || environment || '-' || to_char(day, 'YYYY-MM-DD'),
              service_id,
              tenant_id,
              environment,
              day,
              round(sum(units)::numeric, 6),
              round(sum(cost_inr)::numeric, 4)
            FROM (
              SELECT
                service_id,
                tenant_id,
                environment,
                (occurred_at AT TIME ZONE 'UTC')::date AS day,
                units,
                cost_inr
              FROM usage_events
              WHERE service_id IN :metered
            ) e
            GROUP BY service_id, tenant_id, environment, day
            """
        ).bindparams(sa.bindparam("metered", expanding=True)),
        {"metered": list(METERED_IDS)},
    )

    # Remove estimate services from catalog
    conn.execute(
        sa.text(
            """
            DELETE FROM billing_services
            WHERE id IN :ids
            """
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(ESTIMATE_IDS)},
    )

    # Ensure metered services exist with clean names (no · estimate)
    conn.execute(
        sa.text(
            """
            UPDATE billing_services
            SET name = CASE id
                  WHEN 'llm_chat' THEN 'Azure OpenAI Chat'
                  WHEN 'llm_embed' THEN 'Azure OpenAI Embeddings'
                  WHEN 'stt_az' THEN 'Azure Speech STT'
                  WHEN 'tts_az' THEN 'Azure Speech TTS'
                  ELSE name
                END,
                updated_at = now()
            WHERE id IN :metered
            """
        ).bindparams(sa.bindparam("metered", expanding=True)),
        {"metered": list(METERED_IDS)},
    )

    # Rebuild invoices from real monthly production spend, PER TENANT — usage is
    # recorded with a dynamic tenant_id (usage_meter), so grouping by month only
    # would collapse every tenant's spend onto HDFC. Scope the purge to production
    # so sandbox / other-environment invoices aren't collateral.
    conn.execute(
        sa.text(
            """
            DELETE FROM invoice_line_items
            WHERE invoice_id IN (SELECT id FROM invoices WHERE environment = 'production')
            """
        )
    )
    conn.execute(sa.text("DELETE FROM invoices WHERE environment = 'production'"))

    months = conn.execute(
        sa.text(
            """
            SELECT tenant_id,
                   to_char(usage_date, 'YYYY-MM') AS ym,
                   round(sum(cost_inr)::numeric, 2) AS total
            FROM billing_usage_daily
            WHERE environment = 'production'
            GROUP BY tenant_id, to_char(usage_date, 'YYYY-MM')
            ORDER BY tenant_id, ym
            """
        )
    ).fetchall()

    for tenant_id, ym, total in months:
        # Keep the canonical id for the default tenant; qualify others so their
        # invoice doesn't collide with (or overwrite) HDFC's.
        inv_id = f"INV-{ym}" if tenant_id == "hdfc.retail" else f"INV-{tenant_id}-{ym}"
        # issued on 1st of next month
        y, m = int(ym[:4]), int(ym[5:7])
        if m == 12:
            issued = f"{y + 1}-01-01"
        else:
            issued = f"{y}-{m + 1:02d}-01"
        status = "draft" if ym >= "2026-07" else "paid"
        conn.execute(
            sa.text(
                """
                INSERT INTO invoices (
                  id, tenant_id, invoice_month, environment, total_inr, status, issued_at
                ) VALUES (
                  :id, :tenant, :month, 'production', :total, :status, :issued
                )
                """
            ),
            {
                "id": inv_id,
                "tenant": tenant_id,
                "month": ym,
                "total": float(total or 0),
                "status": status,
                "issued": issued,
            },
        )

    # If no usage yet, still create current-month draft at 0
    has_jul = any(ym == "2026-07" for ym, _ in months)
    if not has_jul:
        conn.execute(
            sa.text(
                """
                INSERT INTO invoices (
                  id, tenant_id, invoice_month, environment, total_inr, status, issued_at
                ) VALUES (
                  'INV-2026-07', 'hdfc.retail', '2026-07', 'production', 0, 'draft', '2026-08-01'
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

    # Budgets sized for metered Azure (not Lakh-scale demo)
    conn.execute(
        sa.text(
            """
            UPDATE budgets SET amount_inr = 5000, updated_at = now()
            WHERE id = 'budget-prod-2026-07'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE budgets SET amount_inr = 1000, updated_at = now()
            WHERE id = 'budget-sandbox-2026-07'
            """
        )
    )

    # Clear staged alert history that referenced fake Lakh-scale spend
    conn.execute(sa.text("DELETE FROM budget_alert_events"))


def downgrade() -> None:
    # Irreversible purge of estimate seed — no-op restore.
    pass
