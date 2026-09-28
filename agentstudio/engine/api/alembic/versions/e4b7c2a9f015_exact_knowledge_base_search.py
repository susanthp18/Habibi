"""Search the knowledge base exactly: drop the IVFFlat index on chunk embeddings.

The index was built with 100 lists, and pgvector probes one list per query by
default, so a search saw about 1% of the chunks and applied the document and
model filters to that sample: "What insurance products do you offer?" returned
nothing, and "Home Protect" returned Fraud and Choice policy text at 0.38 while
Home_policy scored 0.59 (runs 64 and 65, 1,716 chunks). An exact scan over a
knowledge base this size takes milliseconds.

ponytail: exact scan; at ~100k chunks add HNSW with iterative scan
(hnsw.iterative_scan) so the node's document filter still fills the top k.

Revision ID: e4b7c2a9f015
Revises: d6a9c2e4f103
"""

from alembic import op

revision = "e4b7c2a9f015"
down_revision = "d6a9c2e4f103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_ivfflat")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding_ivfflat ON knowledge_base_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
