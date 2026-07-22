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


revision: str = "20260722_0009"
down_revision: Union[str, Sequence[str], None] = "20260722_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Diversify escalation (handoff) reasons across the real taxonomy.
    #    Signal-driven where possible, else spread deterministically by hash.
    op.execute(
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
              ])[(abs(hashtext(h2.id)) % 6) + 1]
            END AS new_reason
          FROM interaction_handoffs h2
          JOIN interactions i ON i.id = h2.interaction_id
        ) sub
        WHERE h.id = sub.id
        """
    )

    # 2a. Non-customer intents (QA-review / empathy-coach) → always a real
    #     customer intent (these leaked in from interaction tags).
    op.execute(
        """
        UPDATE interactions i
        SET primary_intent = (ARRAY[
          'balance','emi','payment-confirm','statement','late-fee',
          'callback','topup','dnd','upi','dispute'
        ])[(abs(hashtext(i.id)) % 10) + 1]
        WHERE i.primary_intent IN ('QA-review', 'empathy-coach')
        """
    )

    # 2b. Null / empty intents → backfill ~85%, leave ~15% uncaptured so the
    #     funnel's "intent captured" stage keeps a real drop.
    op.execute(
        """
        UPDATE interactions i
        SET primary_intent = (ARRAY[
          'balance','emi','payment-confirm','statement','late-fee',
          'callback','topup','dnd','upi','dispute'
        ])[(abs(hashtext(i.id)) % 10) + 1]
        WHERE (i.primary_intent IS NULL OR trim(i.primary_intent) = '')
          AND (abs(hashtext(i.id)) % 20) >= 3
        """
    )


def downgrade() -> None:
    # Restore the original uniform handoff reason. Intent backfill is one-way.
    op.execute("UPDATE interaction_handoffs SET reason = 'routing_rule'")
