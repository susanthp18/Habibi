"""A specialist hop is a row, not an escalation.

Revision ID: 20260908_0114
Revises: 20260908_0113
Create Date: 2026-09-08

``interaction_handoffs`` has always meant "escalated to a human": its reason
CHECK admits eight human-escalation values, so an insert of ``specialist_route``
fails outright. The in-process hop writes one row per hop, which makes this
table two populations rather than one — and three analytics predicates read the
mere existence of a row as escalation.

The widened CHECK and ``db_bot_analytics._ESCALATED_PRED`` ship in the same
commit deliberately. Either alone is a wrong number: the CHECK without the
filter inflates the escalation and containment rates a grievance MIS report is
built on, and the filter without the CHECK gates a hop that cannot be written.

Mirror: sql/04_interactions.sql.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260908_0114"
down_revision: Union[str, None] = "20260908_0113"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REASONS = """(
    'sentiment_drop','verification_failed','compliance','customer_requested',
    'hardship','dispute','high_value','routing_rule',
    'specialist_route','specialist_return','mission_entry'
  )"""

_UP = f"""
ALTER TABLE interaction_handoffs ADD COLUMN IF NOT EXISTS turn_index INTEGER;
ALTER TABLE interaction_handoffs ADD COLUMN IF NOT EXISTS deployment_id TEXT;
ALTER TABLE interaction_handoffs ADD COLUMN IF NOT EXISTS carry TEXT;
ALTER TABLE interaction_handoffs ADD COLUMN IF NOT EXISTS packet jsonb;
ALTER TABLE interaction_handoffs DROP CONSTRAINT IF EXISTS interaction_handoffs_reason_check;
ALTER TABLE interaction_handoffs ADD CONSTRAINT interaction_handoffs_reason_check
  CHECK (reason IN {_REASONS});
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_UP)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
