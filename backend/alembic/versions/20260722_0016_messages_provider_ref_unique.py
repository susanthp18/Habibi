"""messages.provider_ref unique for WhatsApp webhook idempotency.

Revision ID: 20260722_0016
Revises: 20260722_0014
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260722_0016"
down_revision: Union[str, Sequence[str], None] = "20260722_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_provider_ref
        ON messages (provider_ref)
        WHERE provider_ref IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_messages_provider_ref")
