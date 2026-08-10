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
        # A failed CREATE INDEX CONCURRENTLY leaves an *invalid* index behind.
        # IF NOT EXISTS then treats that corpse as success on the retry, so the
        # revision reports applied while the uniqueness guarantee — the whole
        # point of this migration, WhatsApp webhook idempotency — is absent.
        # Drop the invalid leftover first; valid indexes are untouched.
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_index i ON i.indexrelid = c.oid
                WHERE c.relname = 'uq_messages_provider_ref' AND NOT i.indisvalid
              ) THEN
                EXECUTE 'DROP INDEX uq_messages_provider_ref';
              END IF;
            END $$;
            """
        )
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
