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
    # Build CONCURRENTLY so the index creation doesn't take an exclusive lock on
    # `messages` (which would block WhatsApp/voice writes). CONCURRENTLY cannot run
    # inside a transaction, hence the autocommit block. Note: this fails if any
    # duplicate non-null provider_ref rows already exist — dedupe those first.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_messages_provider_ref
            ON messages (provider_ref)
            WHERE provider_ref IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_messages_provider_ref")
