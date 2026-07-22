"""bot analytics seed polish: diversify handoff reasons + backfill intents

The demo seed hardcoded every interaction_handoffs.reason to 'routing_rule'
(so Bot Analytics showed a single escalation reason) and left primary_intent
null on ~two-thirds of interactions (so the intent distribution collapsed into
"Other / unrecognised"). This spreads handoff reasons across the real taxonomy
by interaction signal + a deterministic hash, and backfills customer intents
on the null / non-customer rows while leaving ~15% uncaptured so the funnel's
"intent captured" stage still shows a genuine drop.

Data-only; deterministic (hashtext) so it is reproducible. downgrade restores
the uniform 'routing_rule' reason; intent backfill is one-way (the original
nulls are not recoverable).

Revision ID: 20260722_0009
Revises: 20260722_0008
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0009"
down_revision: Union[str, Sequence[str], None] = "20260722_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Scope every data UPDATE to the demo tenant so this migration can never
# overwrite another tenant's genuine reason / primary_intent values.
# interaction_handoffs has no tenant_id, so it's scoped via its interactions join.
TENANT_ID = "hdfc.retail"


def upgrade() -> None:
    # 1. Diversify escalation (handoff) reasons across the real taxonomy.
    #    Signal-driven where possible, else spread deterministically by hash.
    op.execute(
        sa.text(
            """
            UPDATE interaction_handoffs h
            SET reason = sub.new_reason
            FROM (
              SELECT h2.id,
                CASE
                  WHEN i.avg_sentiment IS NOT NULL AND i.avg_sentiment < -0.30
                    THEN 'sentiment_drop'
                  WHEN lower(coalesce(i.disposition, '')) ~ 'dispute|legal'
                    THEN 'dispute'
                  ELSE (ARRAY[
                    'customer_requested','compliance','hardship',
                    'high_value','verification_failed','routing_rule'
                  ])[(abs(hashtext(h2.id)::bigint) % 6) + 1]
                END AS new_reason
              FROM interaction_handoffs h2
              JOIN interactions i ON i.id = h2.interaction_id
              WHERE i.tenant_id = :tenant
            ) sub
            WHERE h.id = sub.id
            """
        ).bindparams(tenant=TENANT_ID)
    )

    # 2a. Non-customer intents (QA-review / empathy-coach) → always a real
    #     customer intent (these leaked in from interaction tags).
    op.execute(
        sa.text(
            """
            UPDATE interactions i
            SET primary_intent = (ARRAY[
              'balance','emi','payment-confirm','statement','late-fee',
              'callback','topup','dnd','upi','dispute'
            ])[(abs(hashtext(i.id)::bigint) % 10) + 1]
            WHERE i.tenant_id = :tenant
              AND i.primary_intent IN ('QA-review', 'empathy-coach')
            """
        ).bindparams(tenant=TENANT_ID)
    )

    # 2b. Null / empty intents → backfill ~85%, leave ~15% uncaptured so the
    #     funnel's "intent captured" stage keeps a real drop.
    op.execute(
        sa.text(
            """
            UPDATE interactions i
            SET primary_intent = (ARRAY[
              'balance','emi','payment-confirm','statement','late-fee',
              'callback','topup','dnd','upi','dispute'
            ])[(abs(hashtext(i.id)::bigint) % 10) + 1]
            WHERE i.tenant_id = :tenant
              AND (i.primary_intent IS NULL OR trim(i.primary_intent) = '')
              AND (abs(hashtext(i.id)::bigint) % 20) >= 3
            """
        ).bindparams(tenant=TENANT_ID)
    )


def downgrade() -> None:
    # Restore the original uniform handoff reason (demo tenant only). Intent
    # backfill is one-way.
    op.execute(
        sa.text(
            """
            UPDATE interaction_handoffs h
            SET reason = 'routing_rule'
            FROM interactions i
            WHERE i.id = h.interaction_id
              AND i.tenant_id = :tenant
            """
        ).bindparams(tenant=TENANT_ID)
    )
