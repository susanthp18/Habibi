"""billing & usage analytics: schema enrichment + rich seed

Aligns billing_* tables with Habibi /billing screen:
  - billing_services: provider, category, color
  - budgets: environment + nullable tenant_id (org-wide env caps)
  - budget_rules: severity, action, channels jsonb
  - invoices: issued_at
  - unique daily usage key
  - seed 4 tenants, 8 services, ~90d usage, invoices, budgets, alerts

Revision ID: 20260722_0021
Revises: 20260722_0020
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0021"
down_revision: Union[str, Sequence[str], None] = "20260722_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONTH = "2026-07"
AS_OF = date(2026, 7, 22)

SERVICES = [
    {
        "id": "llm_gpt4o",
        "name": "Azure OpenAI GPT-4o",
        "provider": "Azure",
        "category": "LLM",
        "unit": "1K tokens",
        "unit_cost_inr": 0.42,
        "color": "#3b82f6",
        "base": 4800,
    },
    {
        "id": "stt_az",
        "name": "Azure Speech STT",
        "provider": "Azure",
        "category": "Voice",
        "unit": "minute",
        "unit_cost_inr": 0.32,
        "color": "#0ea5e9",
        "base": 2600,
    },
    {
        "id": "tts_az",
        "name": "Azure Speech TTS",
        "provider": "Azure",
        "category": "Voice",
        "unit": "1K chars",
        "unit_cost_inr": 1.4,
        "color": "#14b8a6",
        "base": 2100,
    },
    {
        "id": "tel_twilio",
        "name": "Twilio Voice (IN)",
        "provider": "Twilio",
        "category": "Voice",
        "unit": "minute",
        "unit_cost_inr": 0.85,
        "color": "#f97316",
        "base": 5400,
    },
    {
        "id": "wa_twilio",
        "name": "Twilio WhatsApp BSP",
        "provider": "Twilio",
        "category": "Messaging",
        "unit": "conversation",
        "unit_cost_inr": 0.62,
        "color": "#22c55e",
        "base": 1200,
    },
    {
        "id": "pc_orch",
        "name": "Pipecat Orchestrator",
        "provider": "Pipecat",
        "category": "Infra",
        "unit": "active min",
        "unit_cost_inr": 0.18,
        "color": "#0ea5e9",
        "base": 900,
    },
    {
        "id": "lake_ingest",
        "name": "Data Lake ingest",
        "provider": "Databricks",
        "category": "Infra",
        "unit": "GB",
        "unit_cost_inr": 3.4,
        "color": "#06b6d4",
        "base": 700,
    },
    {
        "id": "infra_flat",
        "name": "Postgres + Redis",
        "provider": "Cloud",
        "category": "Infra",
        "unit": "month",
        "unit_cost_inr": 42000,
        "color": "#64748b",
        "base": 1400,
    },
]

TENANTS = [
    {
        "id": "hdfc.retail",
        "name": "HDFC · Retail Loans",
        "resolved": 21840,
        "aht": 168,
        "budget": 320000,
        "share": 0.42,
    },
    {
        "id": "hdfc.cards",
        "name": "HDFC · Credit Cards",
        "resolved": 15220,
        "aht": 154,
        "budget": 260000,
        "share": 0.28,
    },
    {
        "id": "kotak.pl",
        "name": "Kotak · Personal Loans",
        "resolved": 9420,
        "aht": 191,
        "budget": 180000,
        "share": 0.18,
    },
    {
        "id": "icici.auto",
        "name": "ICICI · Auto Loans",
        "resolved": 6120,
        "aht": 175,
        "budget": 120000,
        "share": 0.12,
    },
]


def _seeded(seed: int):
    s = seed & 0xFFFFFFFF

    def rnd() -> float:
        nonlocal s
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        return s / 0xFFFFFFFF

    return rnd


def upgrade() -> None:
    # --- schema ---
    op.execute(
        """
        ALTER TABLE billing_services
          ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'Unknown',
          ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'Infra',
          ADD COLUMN IF NOT EXISTS color TEXT NOT NULL DEFAULT '#64748b'
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'billing_services_category_check'
          ) THEN
            ALTER TABLE billing_services
              ADD CONSTRAINT billing_services_category_check
              CHECK (category IN ('LLM','Voice','Messaging','Infra'));
          END IF;
        END $$
        """
    )

    op.execute(
        """
        ALTER TABLE budgets
          ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'production'
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'budgets_environment_check'
          ) THEN
            ALTER TABLE budgets
              ADD CONSTRAINT budgets_environment_check
              CHECK (environment IN ('sandbox','production'));
          END IF;
        END $$
        """
    )
    # Org-wide env caps: allow NULL tenant_id
    op.execute("ALTER TABLE budgets ALTER COLUMN tenant_id DROP NOT NULL")

    op.execute(
        """
        ALTER TABLE budget_rules
          ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'warn',
          ADD COLUMN IF NOT EXISTS action TEXT NOT NULL DEFAULT 'Notify',
          ADD COLUMN IF NOT EXISTS channels JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'budget_rules_severity_check'
          ) THEN
            ALTER TABLE budget_rules
              ADD CONSTRAINT budget_rules_severity_check
              CHECK (severity IN ('info','warn','critical'));
          END IF;
        END $$
        """
    )
    # Backfill channels from legacy action_channel when empty
    op.execute(
        """
        UPDATE budget_rules
        SET channels = jsonb_build_array(action_channel)
        WHERE channels = '[]'::jsonb AND action_channel IS NOT NULL AND action_channel <> ''
        """
    )

    op.execute(
        """
        ALTER TABLE invoices
          ADD COLUMN IF NOT EXISTS issued_at date
        """
    )
    op.execute(
        """
        UPDATE invoices
        SET issued_at = created_at::date
        WHERE issued_at IS NULL
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_usage_daily_fact
          ON billing_usage_daily (service_id, tenant_id, environment, usage_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_billing_usage_daily_date
          ON billing_usage_daily (usage_date)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_org_env_month
          ON budgets (environment, month)
          WHERE tenant_id IS NULL
        """
    )

    if not seed_demo_enabled():
        return

    conn = op.get_bind()

    # --- tenants ---
    for t in TENANTS:
        conn.execute(
            sa.text(
                """
                INSERT INTO tenants (
                  id, name, billing_resolved_calls, billing_aht_sec, budget_inr, spend_share
                ) VALUES (
                  :id, :name, :resolved, :aht, :budget, :share
                )
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  billing_resolved_calls = EXCLUDED.billing_resolved_calls,
                  billing_aht_sec = EXCLUDED.billing_aht_sec,
                  budget_inr = EXCLUDED.budget_inr,
                  spend_share = EXCLUDED.spend_share,
                  updated_at = now()
                """
            ),
            t,
        )

    # --- services: clear stub rows that conflict with new catalog ---
    conn.execute(
        sa.text(
            """
            DELETE FROM budget_alert_events
            WHERE budget_rule_id IN (
              SELECT id FROM budget_rules WHERE budget_id IN (
                SELECT id FROM budgets WHERE month = :month OR tenant_id IS NOT NULL
              )
            )
            """
        ),
        {"month": MONTH},
    )
    # Keep alert cleanup limited; wipe usage/invoice stubs then reseed
    conn.execute(sa.text("DELETE FROM invoice_line_items"))
    conn.execute(sa.text("DELETE FROM invoices"))
    conn.execute(sa.text("DELETE FROM billing_usage_daily"))
    conn.execute(
        sa.text(
            """
            DELETE FROM budget_alert_events
            """
        )
    )
    conn.execute(sa.text("DELETE FROM budget_rules"))
    conn.execute(sa.text("DELETE FROM budgets"))
    conn.execute(
        sa.text(
            """
            DELETE FROM billing_services
            WHERE id NOT IN :ids
            """
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": [s["id"] for s in SERVICES]},
    )

    for s in SERVICES:
        conn.execute(
            sa.text(
                """
                INSERT INTO billing_services (
                  id, name, unit, unit_cost_inr, provider, category, color
                ) VALUES (
                  :id, :name, :unit, :unit_cost_inr, :provider, :category, :color
                )
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
                "id": s["id"],
                "name": s["name"],
                "unit": s["unit"],
                "unit_cost_inr": s["unit_cost_inr"],
                "provider": s["provider"],
                "category": s["category"],
                "color": s["color"],
            },
        )

    # --- daily usage (90 days × tenants × services × envs) ---
    rnd = _seeded(20260721)
    rows: list[dict] = []
    for i in range(89, -1, -1):
        d = AS_OF - timedelta(days=i)
        dow = d.weekday()  # Mon=0
        weekend = 0.55 if dow >= 5 else 1.0
        drift = 1 + (90 - i) * 0.008
        for env, env_scale in (("production", 1.0), ("sandbox", 0.08)):
            for t in TENANTS:
                for s in SERVICES:
                    noise = 0.85 + rnd() * 0.3
                    cost = round(s["base"] * weekend * drift * noise * t["share"] * env_scale)
                    unit_cost = float(s["unit_cost_inr"])
                    units = round(cost / unit_cost, 4) if unit_cost > 0 else 0
                    uid = hashlib.sha1(
                        f"{s['id']}|{t['id']}|{env}|{d.isoformat()}".encode()
                    ).hexdigest()[:24]
                    rows.append(
                        {
                            "id": f"bu-{uid}",
                            "service_id": s["id"],
                            "tenant_id": t["id"],
                            "environment": env,
                            "usage_date": d.isoformat(),
                            "units": units,
                            "cost_inr": cost,
                        }
                    )

    # batch insert
    insert_sql = sa.text(
        """
        INSERT INTO billing_usage_daily (
          id, service_id, tenant_id, environment, usage_date, units, cost_inr
        ) VALUES (
          :id, :service_id, :tenant_id, :environment, :usage_date, :units, :cost_inr
        )
        ON CONFLICT (service_id, tenant_id, environment, usage_date) DO UPDATE SET
          units = EXCLUDED.units,
          cost_inr = EXCLUDED.cost_inr
        """
    )
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start + 500]
        for r in chunk:
            conn.execute(insert_sql, r)

    # --- org budgets (current month) ---
    conn.execute(
        sa.text(
            """
            INSERT INTO budgets (id, tenant_id, environment, month, amount_inr)
            VALUES
              ('budget-prod-2026-07', NULL, 'production', :month, 600000),
              ('budget-sandbox-2026-07', NULL, 'sandbox', :month, 40000)
            ON CONFLICT DO NOTHING
            """
        ),
        {"month": MONTH},
    )
    # ON CONFLICT DO NOTHING won't hit without constraint name on insert conflict —
    # use explicit upsert by id
    for bid, env, cap in (
        ("budget-prod-2026-07", "production", 600000),
        ("budget-sandbox-2026-07", "sandbox", 40000),
    ):
        conn.execute(
            sa.text(
                """
                INSERT INTO budgets (id, tenant_id, environment, month, amount_inr)
                VALUES (:id, NULL, :env, :month, :cap)
                ON CONFLICT (id) DO UPDATE SET
                  tenant_id = NULL,
                  environment = EXCLUDED.environment,
                  month = EXCLUDED.month,
                  amount_inr = EXCLUDED.amount_inr,
                  updated_at = now()
                """
            ),
            {"id": bid, "env": env, "month": MONTH, "cap": cap},
        )

    rules = [
        (
            "r1",
            "budget-prod-2026-07",
            70,
            "info",
            "Notify finance-ops",
            ["email:finance-ops"],
        ),
        (
            "r2",
            "budget-prod-2026-07",
            90,
            "warn",
            "Escalate to Slack #billing",
            ["email:finance-ops", "slack:#billing"],
        ),
        (
            "r3",
            "budget-prod-2026-07",
            100,
            "critical",
            "Freeze non-critical batch jobs",
            ["slack:#billing", "pagerduty"],
        ),
        (
            "r4",
            "budget-sandbox-2026-07",
            80,
            "warn",
            "Notify devrel",
            ["email:devrel"],
        ),
        (
            "r5",
            "budget-sandbox-2026-07",
            100,
            "critical",
            "Suspend sandbox keys",
            ["email:devrel"],
        ),
    ]
    for rid, bid, thr, sev, action, channels in rules:
        conn.execute(
            sa.text(
                """
                INSERT INTO budget_rules (
                  id, budget_id, threshold_pct, action_channel, severity, action, channels
                ) VALUES (
                  :id, :budget_id, :thr, :channel, :severity, :action, CAST(:channels AS jsonb)
                )
                ON CONFLICT (id) DO UPDATE SET
                  budget_id = EXCLUDED.budget_id,
                  threshold_pct = EXCLUDED.threshold_pct,
                  action_channel = EXCLUDED.action_channel,
                  severity = EXCLUDED.severity,
                  action = EXCLUDED.action,
                  channels = EXCLUDED.channels,
                  updated_at = now()
                """
            ),
            {
                "id": rid,
                "budget_id": bid,
                "thr": thr,
                "channel": channels[0],
                "severity": sev,
                "action": action,
                "channels": json.dumps(channels),
            },
        )

    alerts = [
        (
            "a1",
            "r1",
            "2026-07-19T14:02:00+00:00",
            420000,
            "Prod spend crossed 70% of monthly cap",
        ),
        (
            "a2",
            "r4",
            "2026-07-14T09:11:00+00:00",
            32000,
            "Sandbox spend crossed 80% of monthly cap",
        ),
        (
            "a3",
            "r1",
            "2026-07-06T22:47:00+00:00",
            420000,
            "Prod spend crossed 70% (recovered)",
        ),
    ]
    for aid, rid, when, spend, msg in alerts:
        conn.execute(
            sa.text(
                """
                INSERT INTO budget_alert_events (
                  id, budget_rule_id, triggered_at, spend_inr, message
                ) VALUES (
                  :id, :rule_id, :when, :spend, :msg
                )
                ON CONFLICT (id) DO UPDATE SET
                  budget_rule_id = EXCLUDED.budget_rule_id,
                  triggered_at = EXCLUDED.triggered_at,
                  spend_inr = EXCLUDED.spend_inr,
                  message = EXCLUDED.message
                """
            ),
            {"id": aid, "rule_id": rid, "when": when, "spend": spend, "msg": msg},
        )

    # --- invoices (last 6 months, production, org rollup on hdfc.retail) ---
    invoice_months = [
        ("INV-2026-02", "2026-02", "Feb 2026", "paid", 498650, "2026-03-01"),
        ("INV-2026-03", "2026-03", "Mar 2026", "paid", 521330, "2026-04-01"),
        ("INV-2026-04", "2026-04", "Apr 2026", "paid", 548910, "2026-05-01"),
        ("INV-2026-05", "2026-05", "May 2026", "paid", 584220, "2026-06-01"),
        ("INV-2026-06", "2026-06", "Jun 2026", "paid", 612430, "2026-07-01"),
        ("INV-2026-07", "2026-07", "Jul 2026", "draft", 0, "2026-08-01"),
    ]
    # Compute Jul draft total from usage MTD production
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
    for inv_id, ym, _label, status, amount, issued in invoice_months:
        total = float(jul_total) if inv_id == "INV-2026-07" else amount
        if inv_id == "INV-2026-07":
            status = "draft"
        conn.execute(
            sa.text(
                """
                INSERT INTO invoices (
                  id, tenant_id, invoice_month, environment, total_inr, status, issued_at
                ) VALUES (
                  :id, 'hdfc.retail', :month, 'production', :total, :status, :issued
                )
                ON CONFLICT (id) DO UPDATE SET
                  invoice_month = EXCLUDED.invoice_month,
                  total_inr = EXCLUDED.total_inr,
                  status = EXCLUDED.status,
                  issued_at = EXCLUDED.issued_at,
                  updated_at = now()
                """
            ),
            {
                "id": inv_id,
                "month": ym,
                "total": total,
                "status": status,
                "issued": issued,
            },
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_budgets_org_env_month")
    op.execute("DROP INDEX IF EXISTS idx_billing_usage_daily_date")
    op.execute("DROP INDEX IF EXISTS uq_billing_usage_daily_fact")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS issued_at")
    op.execute("ALTER TABLE budget_rules DROP COLUMN IF EXISTS channels")
    op.execute("ALTER TABLE budget_rules DROP COLUMN IF EXISTS action")
    op.execute("ALTER TABLE budget_rules DROP COLUMN IF EXISTS severity")
    op.execute("ALTER TABLE budgets DROP COLUMN IF EXISTS environment")
    op.execute("ALTER TABLE billing_services DROP COLUMN IF EXISTS color")
    op.execute("ALTER TABLE billing_services DROP COLUMN IF EXISTS category")
    op.execute("ALTER TABLE billing_services DROP COLUMN IF EXISTS provider")
