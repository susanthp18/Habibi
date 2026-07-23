"""KB schema gaps + partial HNSW + FAQ embeddings

Revision ID: 20260722_0017
Revises: 20260722_0016
Create Date: 2026-07-22

- Add kb_documents tags/embedding_model/last_indexed_at/product_key/source_path
- ADD type CHECK (no prior type CHECK existed)
- Add kb_chunks.chunk_index
- Add faq_pairs.embedding vector(1536)
- Partial HNSW on kb_chunks.embedding WHERE embedding IS NOT NULL
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

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_hnsw
        ON kb_chunks USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_faq_pairs_embedding_hnsw
        ON faq_pairs USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_faq_pairs_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_kb_chunks_embedding_hnsw")
    op.execute("ALTER TABLE faq_pairs DROP COLUMN IF EXISTS embedding")
    op.drop_index("idx_kb_chunks_document_id_chunk_index", table_name="kb_chunks")
    op.drop_column("kb_chunks", "chunk_index")
    op.drop_index("idx_kb_documents_product_key", table_name="kb_documents")
    op.execute("ALTER TABLE kb_documents DROP CONSTRAINT IF EXISTS kb_documents_type_check")
    op.drop_column("kb_documents", "source_path")
    op.drop_column("kb_documents", "product_key")
    op.drop_column("kb_documents", "last_indexed_at")
    op.drop_column("kb_documents", "embedding_model")
    op.drop_column("kb_documents", "tags")
