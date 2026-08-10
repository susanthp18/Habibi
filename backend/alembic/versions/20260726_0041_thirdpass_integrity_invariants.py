"""Third-pass review: integrity invariants and secret hygiene.

* ``uq_kb_chunks_document_id_chunk_index`` — (document_id, chunk_index) is the
  identity of a chunk. Without the unique index an interrupted
  ``_atomic_replace_chunks`` could leave duplicates behind and retrieval
  returned the same passage twice with divergent embeddings.
* ``coaching_actions.tenant_id`` — every other read in followups_db is tenant
  scoped; coaching actions had no column to scope by, so ``list_coaching_actions``
  returned every tenant's rows.
* Purge signing secrets / bearer tokens that were persisted into
  ``webhook_endpoint_headers`` before the write-side exclusion existed. The read
  path now filters them case-insensitively, but they must not sit at rest.

Revision ID: 20260726_0041
Revises: 20260725_0040
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0041"
down_revision: Union[str, Sequence[str], None] = "20260725_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    conn = op.get_bind()

    # --- kb_chunks: one row per (document, chunk_index) --------------------
    # Dedupe first; keep the most recently updated row for each pair.
    conn.execute(
        sa.text(
            """
            DELETE FROM kb_chunks c
            USING kb_chunks keep
            WHERE keep.document_id = c.document_id
              AND keep.chunk_index = c.chunk_index
              AND (keep.updated_at, keep.id) > (c.updated_at, c.id)
            """
        )
    )
    op.execute("DROP INDEX IF EXISTS idx_kb_chunks_document_id_chunk_index")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_document_id_chunk_index
          ON kb_chunks (document_id, chunk_index)
        """
    )

    # --- coaching_actions: explicit tenant --------------------------------
    op.add_column("coaching_actions", sa.Column("tenant_id", sa.Text(), nullable=True))
    # Backfill only through a link that actually identifies the owner. The
    # arbitrary `first tenant by id` and demo-tenant fallbacks that used to
    # close this COALESCE silently attributed unresolvable coaching records to
    # whichever tenant sorted first — the opposite of what a tenant-isolation
    # migration is for, and undetectable afterwards.
    conn.execute(
        sa.text(
            """
            UPDATE coaching_actions ca
            SET tenant_id = COALESCE(
                  (SELECT i.tenant_id FROM interactions i WHERE i.id = ca.interaction_id),
                  (SELECT u.tenant_id FROM users u WHERE u.id = ca.subject_user_id),
                  (SELECT b.tenant_id FROM bots b WHERE b.id = ca.subject_bot_id)
                )
            WHERE tenant_id IS NULL
            """
        )
    )
    # Anything still unscoped is an orphan we must not guess about and must not
    # destroy: fail the migration so an operator resolves it deliberately.
    orphans = conn.execute(
        sa.text("SELECT count(*) FROM coaching_actions WHERE tenant_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} coaching_actions rows have no interaction, subject user or "
            "subject bot to derive tenant_id from. Resolve or delete them, then "
            "re-run this migration."
        )
    op.alter_column("coaching_actions", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_coaching_actions_tenant",
        "coaching_actions",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_coaching_actions_tenant_id", "coaching_actions", ["tenant_id"]
    )

    # --- webhook headers: drop persisted secrets ---------------------------
    conn.execute(
        sa.text(
            """
            DELETE FROM webhook_endpoint_headers
            WHERE lower(header_key) IN (
              'x-webhook-secret-sha256', 'x-webhook-secret', 'authorization'
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_coaching_actions_tenant_id", table_name="coaching_actions")
    op.drop_constraint("fk_coaching_actions_tenant", "coaching_actions", type_="foreignkey")
    op.drop_column("coaching_actions", "tenant_id")

    op.execute("DROP INDEX IF EXISTS uq_kb_chunks_document_id_chunk_index")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id_chunk_index
          ON kb_chunks (document_id, chunk_index)
        """
    )
    # Deleted secret headers are not restored — that is the point of the purge.
