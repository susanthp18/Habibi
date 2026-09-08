"""Cadence carries the card: call_cadence_state.bot_id, .escalate_to.

Revision ID: 20260906_0112
Revises: 20260906_0111
Create Date: 2026-09-06

NOT applied to the running database by this work package. Mirror:
sql/22_campaigns.sql (call_cadence_state.bot_id, .escalate_to).

Measured on collections (2026-09-06, alembic 20260905_0106):
  call_cadence_state=0 rows (0 open, 0 with a last_attempt_id),
  call_attempts=22 all carrying bot_id across 1 distinct bot.
  The backfill therefore touches 0 rows today. It is written anyway
  because the ladder is created lazily at the first outcome, so the
  table is empty between campaigns rather than permanently.

Backfill reads the bot off the ladder's own last attempt. That is the
agent that actually spoke, which is the only defensible answer; guessing
the tenant default is the bug this column exists to end. A row whose
last attempt is gone stays NULL and resolves through
``mission.resolve_outbound_bot_id`` at claim time.

``escalate_to`` records who the published card says owns a case whose
ladder ran out. No backfill: the column is written when a ladder is
exhausted, and re-deriving it for ladders already closed would put a
card's present opinion on a case that ended under a different one.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260906_0112"
down_revision: Union[str, None] = "20260906_0111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE call_cadence_state ADD COLUMN IF NOT EXISTS bot_id TEXT")
    op.execute("ALTER TABLE call_cadence_state ADD COLUMN IF NOT EXISTS escalate_to TEXT")
    op.execute(
        """
        UPDATE call_cadence_state s
        SET bot_id = a.bot_id
        FROM call_attempts a
        WHERE a.id = s.last_attempt_id
          AND s.bot_id IS NULL
          AND a.bot_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE call_cadence_state DROP COLUMN IF EXISTS escalate_to")
    op.execute("ALTER TABLE call_cadence_state DROP COLUMN IF EXISTS bot_id")
