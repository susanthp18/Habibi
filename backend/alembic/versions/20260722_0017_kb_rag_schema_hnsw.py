"""KB schema gaps + partial HNSW + FAQ embeddings

Revision ID: 20260722_0017
Revises: 20260722_0016
Create Date: 2026-07-22

- Add kb_documents tags/embedding_model/last_indexed_at/product_key/source_path
- ADD type CHECK (no prior type CHECK existed)
- Add kb_chunks.chunk_index
- Add faq_pairs.embedding vector(1536)
- Partial HNSW on kb_chunks.embedding WHERE embedding IS NOT NULL

Note: live databases that already have these HNSW indexes should skip any
repair; new environments prefer CREATE INDEX CONCURRENTLY outside a txn when
rebuilding under load (not rewriteable here — upgrade already stamped).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260722_0017"
down_revision: Union[str, Sequence[str], None] = "20260722_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: safe if a prior collided 0015 partially applied these objects.
    op.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS tags jsonb DEFAULT '[]'::jsonb NOT NULL")
    op.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS embedding_model text")
    op.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS last_indexed_at timestamptz")
    op.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS product_key text")
    op.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS source_path text")

    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'kb_documents_type_check'
          ) THEN
            ALTER TABLE kb_documents
            ADD CONSTRAINT kb_documents_type_check
            CHECK (type IN ('policy','sop','product','compliance','faq','benefits'));
          END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_kb_documents_product_key ON kb_documents (product_key)")

    op.execute("ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS chunk_index integer")
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (PARTITION BY document_id ORDER BY created_at, id) AS rn
          FROM kb_chunks
          WHERE chunk_index IS NULL
        )
        UPDATE kb_chunks c
        SET chunk_index = ranked.rn
        FROM ranked
        WHERE c.id = ranked.id
        """
    )
    op.execute("UPDATE kb_chunks SET chunk_index = 1 WHERE chunk_index IS NULL")
    op.execute("ALTER TABLE kb_chunks ALTER COLUMN chunk_index SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id_chunk_index "
        "ON kb_chunks (document_id, chunk_index)"
    )

    op.execute("ALTER TABLE faq_pairs ADD COLUMN IF NOT EXISTS embedding vector(1536)")

    # CONCURRENTLY inside an autocommit_block (same pattern as
    # uq_messages_provider_ref): an HNSW build over a populated kb_chunks takes
    # minutes and a plain CREATE INDEX holds an ACCESS EXCLUSIVE lock for the
    # duration — every retrieval blocks until it finishes.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kb_chunks_embedding_hnsw
            ON kb_chunks USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_faq_pairs_embedding_hnsw
            ON faq_pairs USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL
            """
        )


def downgrade() -> None:
    # Every DROP is IF EXISTS: the HNSW index builds in upgrade() can fail
    # partway (pgvector missing, memory limits), and a downgrade that aborts on
    # the first already-absent object leaves the database wedged between
    # revisions with no way forward or back.
    op.execute("DROP INDEX IF EXISTS idx_faq_pairs_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_kb_chunks_embedding_hnsw")
    op.execute("ALTER TABLE faq_pairs DROP COLUMN IF EXISTS embedding")
    op.execute("DROP INDEX IF EXISTS idx_kb_chunks_document_id_chunk_index")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN IF EXISTS chunk_index")
    op.execute("DROP INDEX IF EXISTS idx_kb_documents_product_key")
    op.execute("ALTER TABLE kb_documents DROP CONSTRAINT IF EXISTS kb_documents_type_check")
    for column in ("source_path", "product_key", "last_indexed_at", "embedding_model", "tags"):
        op.execute(f"ALTER TABLE kb_documents DROP COLUMN IF EXISTS {column}")
