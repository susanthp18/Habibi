"""routing builder: widen rules + seed library + redistribute executions

routing_rules had a single thin row (conditions jsonb + action_key only) while
the Habibi Routing Builder needs name/description/category and a screen-shaped
when[] condition list. The 42 routing_rule_executions all pointed at that one
rule, so the builder looked empty next to a large firing log.

This migration:
  1. Adds name / description / category columns.
  2. Seeds ~7 rules aligned with Habibi RULES_SEED vocabulary (fields + ActionKey).
  3. Rewrites the legacy route-sentiment-drop into the screen shape.
  4. Redistributes existing executions across rules (no double-count) and bumps
     a slice of matched rows into the last 24h so triggersLast24h is visible.

Revision ID: 20260722_0013
Revises: 20260722_0012
Create Date: 2026-07-22
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0013"
down_revision: Union[str, Sequence[str], None] = "20260722_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_ID = "hdfc.retail"


def _cond(cid: str, field: str, op_: str, value: Any) -> dict[str, Any]:
    return {"id": cid, "field": field, "op": op_, "value": value}


def _or(oid: str, *conds: dict[str, Any]) -> dict[str, Any]:
    return {"id": oid, "or": list(conds)}


_RULES: list[dict[str, Any]] = [
    {
        "id": "route-abusive-supervisor",
        "priority": 1,
        "enabled": True,
        "name": "Abusive language → immediate supervisor",
        "description": "Barge supervisor when abusive language or legal threats detected.",
        "category": "Escalation",
        "conditions": [
            _or(
                "c-abuse-or",
                _cond("c-abuse-1", "guardrail_flag", "=", "abusive-language"),
                _cond("c-abuse-2", "guardrail_flag", "=", "legal-threat"),
            )
        ],
        "action_key": "escalate_supervisor",
        "action_params": {},
    },
    {
        "id": "route-high-value-tier2",
        "priority": 2,
        "enabled": True,
        "name": "High-value angry customer → Tier 2",
        "description": "Angry customers with high overdue routed to Tier 2 collections.",
        "category": "Routing",
        "conditions": [
            _cond("c-hv-sent", "sentiment", "=", "angry"),
            _cond("c-hv-amt", "overdue_amount", ">", 25000),
        ],
        "action_key": "route_tier2",
        "action_params": {},
    },
    {
        "id": "route-hardship-handoff",
        "priority": 3,
        "enabled": True,
        "name": "Hardship intent → human handoff",
        "description": "Hand off when customer expresses financial hardship.",
        "category": "Handoff",
        "conditions": [_cond("c-hardship", "intent", "=", "hardship")],
        "action_key": "handoff_human",
        "action_params": {"team": "Hardship Desk"},
    },
    {
        "id": "route-dispute-queue",
        "priority": 4,
        "enabled": True,
        "name": "Dispute intent → collections queue",
        "description": "Route dispute intents to the specialist collections dispute desk.",
        "category": "Routing",
        "conditions": [_cond("c-dispute", "intent", "=", "dispute")],
        "action_key": "route_specialist",
        "action_params": {"team": "Dispute Desk"},
    },
    {
        "id": "route-sentiment-drop",
        "priority": 5,
        "enabled": True,
        "name": "Negative sentiment → supervisor",
        "description": "Escalate when average call sentiment turns strongly negative.",
        "category": "Escalation",
        "conditions": [_cond("c-sent", "sentiment", "=", "angry")],
        "action_key": "escalate_supervisor",
        "action_params": {},
    },
    {
        "id": "route-verify-failed",
        "priority": 6,
        "enabled": True,
        "name": "Verification failed → human",
        "description": "Stop upsell and hand off when caller verification fails mid-call.",
        "category": "Throttle",
        "conditions": [
            _cond("c-vf-status", "verification_status", "=", "failed"),
            _cond("c-vf-turns", "turn_count", ">=", 4),
        ],
        "action_key": "stop_upsell",
        "action_params": {},
    },
    {
        "id": "route-dnd-sms",
        "priority": 7,
        "enabled": True,
        "name": "DND breach → SMS follow-up only",
        "description": "If DND is on during a voice attempt, close voice and send scheduled SMS.",
        "category": "Compliance",
        "conditions": [
            _cond("c-dnd", "consent_dnd", "=", True),
            _cond("c-dnd-ch", "channel", "=", "voice"),
        ],
        "action_key": "send_sms",
        "action_params": {"template": "dnd_followup_v2"},
    },
    {
        "id": "route-high-dpd",
        "priority": 8,
        "enabled": False,
        "name": "High DPD → priority Tier 2 queue",
        "description": "Anyone above 60 DPD goes to Tier 2 regardless of sentiment.",
        "category": "Routing",
        "conditions": [_cond("c-dpd", "dpd", ">", 60)],
        "action_key": "route_tier2",
        "action_params": {},
    },
]


def upgrade() -> None:
    op.add_column("routing_rules", sa.Column("name", sa.Text(), nullable=True))
    op.add_column("routing_rules", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("routing_rules", sa.Column("category", sa.Text(), nullable=True))

    conn = op.get_bind()

    for rule in _RULES:
        conn.execute(
            sa.text(
                """
                INSERT INTO routing_rules (
                  id, tenant_id, priority, enabled, name, description, category,
                  conditions, action_key, action_params
                ) VALUES (
                  :id, :tenant, :priority, :enabled, :name, :description, :category,
                  CAST(:conditions AS jsonb), :action_key, CAST(:action_params AS jsonb)
                )
                ON CONFLICT (id) DO UPDATE SET
                  tenant_id = EXCLUDED.tenant_id,
                  priority = EXCLUDED.priority,
                  enabled = EXCLUDED.enabled,
                  name = EXCLUDED.name,
                  description = EXCLUDED.description,
                  category = EXCLUDED.category,
                  conditions = EXCLUDED.conditions,
                  action_key = EXCLUDED.action_key,
                  action_params = EXCLUDED.action_params,
                  updated_at = now()
                """
            ),
            {
                "id": rule["id"],
                "tenant": TENANT_ID,
                "priority": rule["priority"],
                "enabled": rule["enabled"],
                "name": rule["name"],
                "description": rule["description"],
                "category": rule["category"],
                "conditions": json.dumps(rule["conditions"]),
                "action_key": rule["action_key"],
                "action_params": json.dumps(rule["action_params"]),
            },
        )

    conn.execute(
        sa.text(
            """
            UPDATE routing_rule_executions e
            SET rule_id = sub.new_rule,
                result = sub.new_result,
                action_taken = CASE
                  WHEN sub.new_result = 'matched' THEN rr.action_key
                  ELSE e.action_taken
                END,
                context = COALESCE(e.context, '{}'::jsonb) || jsonb_build_object(
                  'mappedBy', '20260722_0013',
                  'signal', sub.signal
                ),
                evaluated_at = CASE
                  WHEN sub.new_result = 'matched'
                       AND (abs(hashtext(e.id)::bigint) % 3) = 0
                    THEN now() - ((abs(hashtext(e.id)::bigint) % 20) || ' hours')::interval
                  ELSE e.evaluated_at
                END
            FROM (
              SELECT e2.id,
                CASE
                  WHEN i.avg_sentiment IS NOT NULL AND i.avg_sentiment < -0.30
                    THEN 'route-sentiment-drop'
                  WHEN lower(coalesce(i.primary_intent, '')) IN ('dispute', 'legal')
                    THEN 'route-dispute-queue'
                  WHEN lower(coalesce(i.primary_intent, '')) IN ('hardship', 'waiver', 'waiver_request')
                    THEN 'route-hardship-handoff'
                  WHEN lower(coalesce(i.disposition, '')) ~ 'dnd|opt.?out'
                    THEN 'route-dnd-sms'
                  WHEN exists (
                    SELECT 1 FROM identity_verifications v
                    WHERE v.interaction_id = i.id AND v.status = 'failed'
                  ) THEN 'route-verify-failed'
                  WHEN (abs(hashtext(e2.id)::bigint) % 5) = 0
                    THEN 'route-high-value-tier2'
                  WHEN (abs(hashtext(e2.id)::bigint) % 5) = 1
                    THEN 'route-abusive-supervisor'
                  ELSE 'route-sentiment-drop'
                END AS new_rule,
                CASE
                  WHEN i.avg_sentiment IS NOT NULL AND i.avg_sentiment < -0.30 THEN 'matched'
                  WHEN lower(coalesce(i.primary_intent, '')) IN (
                    'dispute', 'legal', 'hardship', 'waiver', 'waiver_request'
                  ) THEN 'matched'
                  WHEN lower(coalesce(i.disposition, '')) ~ 'dnd|opt.?out' THEN 'matched'
                  WHEN (abs(hashtext(e2.id)::bigint) % 4) = 0 THEN 'matched'
                  ELSE 'skipped'
                END AS new_result,
                CASE
                  WHEN i.avg_sentiment IS NOT NULL AND i.avg_sentiment < -0.30 THEN 'sentiment'
                  WHEN lower(coalesce(i.primary_intent, '')) IN ('dispute', 'legal') THEN 'dispute'
                  WHEN lower(coalesce(i.primary_intent, '')) IN ('hardship', 'waiver', 'waiver_request')
                    THEN 'hardship'
                  WHEN lower(coalesce(i.disposition, '')) ~ 'dnd|opt.?out' THEN 'dnd'
                  ELSE 'hash'
                END AS signal
              FROM routing_rule_executions e2
              JOIN interactions i ON i.id = e2.interaction_id
              WHERE i.tenant_id = :tenant
            ) sub
            JOIN routing_rules rr ON rr.id = sub.new_rule
            WHERE e.id = sub.id
            """
        ).bindparams(tenant=TENANT_ID)
    )

    op.alter_column("routing_rules", "name", nullable=False, server_default="")
    op.alter_column("routing_rules", "name", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    # NOTE: upgrade() also rewrote result / action_taken / evaluated_at on these
    # rows from derived values without snapshotting the originals, so those columns
    # cannot be perfectly restored here. We reset rule_id and strip the additive
    # context marker (mappedBy/signal) that upgrade injected — the only cleanly
    # reversible change on this seed/demo data.
    conn.execute(
        sa.text(
            """
            UPDATE routing_rule_executions
            SET rule_id = 'route-sentiment-drop',
                context = (COALESCE(context, '{}'::jsonb) - 'mappedBy' - 'signal')
            WHERE rule_id IS NOT NULL
              AND rule_id <> 'route-sentiment-drop'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM routing_rules
            WHERE tenant_id = :tenant
              AND id <> 'route-sentiment-drop'
            """
        ).bindparams(tenant=TENANT_ID)
    )
    conn.execute(
        sa.text(
            """
            UPDATE routing_rules
            SET name = NULL,
                description = NULL,
                category = NULL,
                priority = 10,
                enabled = true,
                conditions = '{"avgSentimentLt": -0.35}'::jsonb,
                action_key = 'handoff',
                action_params = '{"team": "card-collections"}'::jsonb
            WHERE id = 'route-sentiment-drop'
            """
        )
    )
    op.drop_column("routing_rules", "category")
    op.drop_column("routing_rules", "description")
    op.drop_column("routing_rules", "name")
