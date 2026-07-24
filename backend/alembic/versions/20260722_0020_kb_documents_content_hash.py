"""Alembic: kb_documents.content_hash for no-op re-index skip (KB-4).

Revision ID: 20260722_0020
Revises: 20260722_0019
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260722_0020"
down_revision: Union[str, Sequence[str], None] = "20260722_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS content_hash text")


def downgrade() -> None:
    op.execute("ALTER TABLE kb_documents DROP COLUMN IF EXISTS content_hash")
