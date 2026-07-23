"""Add intent columns on interaction_transcript for live capture (Phase 0).

Revision ID: 20260722_0027
Revises: 20260722_0026
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260722_0027"
down_revision: Union[str, Sequence[str], None] = "20260722_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE interaction_transcript
          ADD COLUMN IF NOT EXISTS intent TEXT,
          ADD COLUMN IF NOT EXISTS intent_score numeric(5,3)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_interaction_transcript_intent
          ON interaction_transcript (interaction_id, intent)
          WHERE intent IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_interaction_transcript_intent")
    op.execute(
        """
        ALTER TABLE interaction_transcript
          DROP COLUMN IF EXISTS intent_score,
          DROP COLUMN IF EXISTS intent
        """
    )
