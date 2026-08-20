"""Agent card lifecycle — archive instead of delete.

Revision ID: 20260817_0081
Revises: 20260815_0080
Create Date: 2026-08-17

Mirrors sql/20_agent_card_lifecycle.sql. SQL is inlined so alembic does not
depend on a sibling Path read at upgrade time.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260817_0081"
down_revision: Union[str, Sequence[str], None] = "20260815_0080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bots_archived_at ON bots (archived_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_bots_archived_at")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS archived_at")
