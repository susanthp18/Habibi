"""phase 3a mutation support

Revision ID: 20260721_0002
Revises: 20260721_0001
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260721_0002"
down_revision: Union[str, Sequence[str], None] = "20260721_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_idempotency_keys_endpoint", "idempotency_keys", ["endpoint"])


def downgrade() -> None:
    op.drop_index("idx_idempotency_keys_endpoint", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

