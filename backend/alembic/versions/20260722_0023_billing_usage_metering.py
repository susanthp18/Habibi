"""billing: live usage_events + real Azure price book + backfill

- usage_events: per-call metering from Azure OpenAI / Speech
- Replace synthetic llm/stt/tts burn with metered services + real INR rates
- Backfill chat from sandbox_run_turns; embeds from kb_chunks.tokens

Revision ID: 20260722_0023
Revises: 20260722_0022
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0023"
down_revision: Union[str, Sequence[str], None] = "20260722_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AS_OF = date(2026, 7, 22)
FX = 86.0
# GPT-5-mini class defaults
CHAT_IN_USD_1M = 0.25
CHAT_OUT_USD_1M = 2.00
EMBED_USD_1M = 0.02
TTS_USD_1M_CHARS = 15.0
STT_USD_HOUR = 1.0


def _chat_cost(prompt: int, completion: int) -> float:
    usd = (prompt / 1_000_000) * CHAT_IN_USD_1M + (completion / 1_000_000) * CHAT_OUT_USD_1M
    return round(usd * FX, 6)


def _embed_cost(tokens: int) -> float:
    return round((tokens / 1_000_000) * EMBED_USD_1M * FX, 6)


def _blended_chat_per_1k() -> float:
    return round((((0.7 * CHAT_IN_USD_1M) + (0.3 * CHAT_OUT_USD_1M)) / 1000.0) * FX, 4)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
          service_id TEXT NOT NULL REFERENCES billing_services(id),
          units numeric(18,6) NOT NULL,
          cost_inr numeric(14,6) NOT NULL,
          meta JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at timestamptz NOT NULL DEFAULT now(),
          source_ref TEXT,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_usage_events_service_env
          ON usage_events (service_id, tenant_id, environment, occurred_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_usage_events_occurred
          ON usage_events (occurred_at DESC)
        """
    )

    if not seed_demo_enabled():
        return

    conn = op.get_bind()

    # Clear synthetic Azure-ish burn; keep infra/messaging estimates for now.
    conn.execute(
        sa.text(
            """
            DELETE FROM billing_usage_daily
            WHERE service_id IN (
              'llm_gpt4o', 'llm_chat', 'llm_embed', 'stt_az', 'tts_az'
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM invoice_line_items
            WHERE service_id IN ('llm_gpt4o', 'svc-voice-minutes', 'svc-rag-query')
            """
        )
    )

    # Retire old llm_gpt4o id → llm_chat
    conn.execute(
        sa.text(
            """
            INSERT INTO billing_services (
              id, name, unit, unit_cost_inr, provider, category, color
            ) VALUES
              (:chat_id, 'Azure OpenAI Chat', '1K tokens', :chat_cost, 'Azure', 'LLM', '#3b82f6'),
              (:embed_id, 'Azure OpenAI Embeddings', '1K tokens', :embed_cost, 'Azure', 'LLM', '#6366f1')
            ON CONFLICT (id) DO UPDATE SET
              name = EXCLUDED.name,
              unit = EXCLUDED.unit,
              unit_cost_inr = EXCLUDED.unit_cost_inr,
              provider = EXCLUDED.provider,
              category = EXCLUDED.category,
              color = EXCLUDED.color,
              updated_at = now()
            """
        ),
        {
            "chat_id": "llm_chat",
            "embed_id": "llm_embed",
            "chat_cost": _blended_chat_per_1k(),
            "embed_cost": round((EMBED_USD_1M / 1000.0) * FX, 4),
        },
    )
    conn.execute(
        sa.text(
            """
            UPDATE billing_services SET
              name = :name,
              unit = :unit,
              unit_cost_inr = :uc,
              provider = 'Azure',
              category = 'Voice',
              color = :color,
              updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": "stt_az",
            "name": "Azure Speech STT",
            "unit": "minute",
            "uc": round((STT_USD_HOUR / 60.0) * FX, 4),
            "color": "#0ea5e9",
        },
    )
    conn.execute(
        sa.text(
            """
            UPDATE billing_services SET
              name = :name,
              unit = :unit,
              unit_cost_inr = :uc,
              provider = 'Azure',
              category = 'Voice',
              color = :color,
              updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": "tts_az",
            "name": "Azure Speech TTS",
            "unit": "1K chars",
            "uc": round((TTS_USD_1M_CHARS / 1000.0) * FX, 4),
            "color": "#14b8a6",
        },
    )
    # Drop obsolete catalog row if unused
    conn.execute(
        sa.text(
            """
            DELETE FROM billing_services
            WHERE id = 'llm_gpt4o'
              AND NOT EXISTS (
                SELECT 1 FROM billing_usage_daily d WHERE d.service_id = 'llm_gpt4o'
              )
              AND NOT EXISTS (
                SELECT 1 FROM invoice_line_items i WHERE i.service_id = 'llm_gpt4o'
              )
            """
        )
    )

    # Mark non-metered services clearly in the name (estimates)
    for sid, name in (
        ("tel_twilio", "Twilio Voice (IN) · estimate"),
        ("wa_twilio", "WhatsApp messaging · estimate"),
        ("pc_orch", "Pipecat Orchestrator · estimate"),
        ("lake_ingest", "Data Lake ingest · estimate"),
        ("infra_flat", "Postgres + Redis · estimate"),
    ):
        conn.execute(
            sa.text(
                """
                UPDATE billing_services
                SET name = :name, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": sid, "name": name},
        )

    # ---- Backfill chat from sandbox turns (real token_count) ----
    turns = conn.execute(
        sa.text(
            """
            SELECT t.id, t.token_count, t.latency_ms, t.created_at,
                   coalesce(r.started_by_user_id, 'system') AS actor
            FROM sandbox_run_turns t
            JOIN sandbox_runs r ON r.id = t.run_id
            WHERE coalesce(t.token_count, 0) > 0
            """
        )
    ).fetchall()

    for row in turns:
        tokens = int(row[1] or 0)
        if tokens <= 0:
            continue
        prompt = int(tokens * 0.7)
        completion = tokens - prompt
        cost = _chat_cost(prompt, completion)
        units = round(tokens / 1000.0, 6)
        occurred = row[3] or datetime.now(timezone.utc)
        if isinstance(occurred, datetime) and occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        day = occurred.date() if isinstance(occurred, datetime) else AS_OF
        eid = f"ue-bf-chat-{row[0]}"
        conn.execute(
            sa.text(
                """
                INSERT INTO usage_events (
                  id, tenant_id, environment, service_id, units, cost_inr,
                  meta, occurred_at, source_ref
                ) VALUES (
                  :id, 'hdfc.retail', 'production', 'llm_chat', :units, :cost,
                  CAST(:meta AS jsonb), :when, :ref
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": eid,
                "units": units,
                "cost": cost,
                "meta": json.dumps(
                    {
                        "promptTokens": prompt,
                        "completionTokens": completion,
                        "backfill": "sandbox_run_turns",
                    }
                ),
                "when": occurred,
                "ref": f"sandbox_turn:{row[0]}",
            },
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO billing_usage_daily (
                  id, service_id, tenant_id, environment, usage_date, units, cost_inr
                ) VALUES (
                  :id, 'llm_chat', 'hdfc.retail', 'production', :day, :units, :cost
                )
                ON CONFLICT (service_id, tenant_id, environment, usage_date) DO UPDATE SET
                  units = billing_usage_daily.units + EXCLUDED.units,
                  cost_inr = billing_usage_daily.cost_inr + EXCLUDED.cost_inr
                """
            ),
            {
                "id": f"bu-llm_chat-hdfc.retail-production-{day.isoformat()}",
                "day": day.isoformat(),
                "units": units,
                "cost": round(cost, 4),
            },
        )

    # ---- Backfill embeds from kb_chunks.tokens (one-shot ingest cost) ----
    # Spread across last 14 days so charts aren't a single spike.
    chunk_tokens = conn.execute(
        sa.text("SELECT coalesce(sum(tokens), 0) FROM kb_chunks WHERE tokens IS NOT NULL")
    ).scalar()
    total_embed_tokens = int(chunk_tokens or 0)
    if total_embed_tokens > 0:
        per_day = max(1, total_embed_tokens // 14)
        remainder = total_embed_tokens - per_day * 14
        for i in range(14):
            day = AS_OF - timedelta(days=13 - i)
            toks = per_day + (remainder if i == 13 else 0)
            cost = _embed_cost(toks)
            units = round(toks / 1000.0, 6)
            eid = f"ue-bf-embed-{day.isoformat()}"
            when = datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc)
            conn.execute(
                sa.text(
                    """
                    INSERT INTO usage_events (
                      id, tenant_id, environment, service_id, units, cost_inr,
                      meta, occurred_at, source_ref
                    ) VALUES (
                      :id, 'hdfc.retail', 'production', 'llm_embed', :units, :cost,
                      CAST(:meta AS jsonb), :when, 'kb_chunks_backfill'
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": eid,
                    "units": units,
                    "cost": cost,
                    "meta": json.dumps({"promptTokens": toks, "backfill": "kb_chunks.tokens"}),
                    "when": when,
                },
            )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO billing_usage_daily (
                      id, service_id, tenant_id, environment, usage_date, units, cost_inr
                    ) VALUES (
                      :id, 'llm_embed', 'hdfc.retail', 'production', :day, :units, :cost
                    )
                    ON CONFLICT (service_id, tenant_id, environment, usage_date) DO UPDATE SET
                      units = EXCLUDED.units,
                      cost_inr = EXCLUDED.cost_inr
                    """
                ),
                {
                    "id": f"bu-llm_embed-hdfc.retail-production-{day.isoformat()}",
                    "day": day.isoformat(),
                    "units": units,
                    "cost": round(cost, 4),
                },
            )

    # Light STT/TTS seed from Prompt Studio activity is zero until live calls;
    # leave empty so charts only show metered Azure LLM until Speech is used.

    # Shrink estimate services to ~10% of previous synthetic so they don't dominate.
    conn.execute(
        sa.text(
            """
            UPDATE billing_usage_daily
            SET units = round(units * 0.1, 4),
                cost_inr = round(cost_inr * 0.1, 2)
            WHERE service_id IN (
              'tel_twilio', 'wa_twilio', 'pc_orch', 'lake_ingest', 'infra_flat'
            )
            """
        )
    )

    # Refresh Jul draft invoice total from remaining usage
    jul_total = conn.execute(
        sa.text(
            """
            SELECT coalesce(sum(cost_inr), 0)
            FROM billing_usage_daily
            WHERE environment = 'production'
              AND usage_date >= '2026-07-01'
              AND usage_date <= :as_of
            """
        ),
        {"as_of": AS_OF.isoformat()},
    ).scalar()
    conn.execute(
        sa.text(
            """
            UPDATE invoices
            SET total_inr = :total, updated_at = now()
            WHERE id = 'INV-2026-07'
            """
        ),
        {"total": float(jul_total or 0)},
    )

    # Align org budget caps to metered reality (lower for demo with real prices)
    conn.execute(
        sa.text(
            """
            UPDATE budgets SET amount_inr = 50000, updated_at = now()
            WHERE id = 'budget-prod-2026-07'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE budgets SET amount_inr = 5000, updated_at = now()
            WHERE id = 'budget-sandbox-2026-07'
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_usage_events_occurred")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_service_env")
    op.execute("DROP TABLE IF EXISTS usage_events")
