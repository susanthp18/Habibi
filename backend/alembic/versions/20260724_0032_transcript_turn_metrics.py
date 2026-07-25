"""Add per-turn latency/token columns on interaction_transcript.

Schema-only. CrmSink attaches TTFB/TTFA/tokens to bot turns when available.

Revision ID: 20260724_0032
Revises: 20260724_0031
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260724_0032"
down_revision: Union[str, Sequence[str], None] = "20260724_0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE interaction_transcript ADD COLUMN IF NOT EXISTS ttfb_ms INTEGER"
    )
    op.execute(
        "ALTER TABLE interaction_transcript ADD COLUMN IF NOT EXISTS ttfa_ms INTEGER"
    )
    op.execute(
        "ALTER TABLE interaction_transcript ADD COLUMN IF NOT EXISTS tokens INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE interaction_transcript DROP COLUMN IF EXISTS tokens")
    op.execute("ALTER TABLE interaction_transcript DROP COLUMN IF EXISTS ttfa_ms")
    op.execute("ALTER TABLE interaction_transcript DROP COLUMN IF EXISTS ttfb_ms")
