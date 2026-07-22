"""dispute resolution notes

Persists the resolution / rejection rationale captured on the Disputes screen.
Previously the UI collected these notes and silently dropped them.

Revision ID: 20260722_0003
Revises: 20260721_0002
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0003"
down_revision: Union[str, Sequence[str], None] = "20260721_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("disputes", sa.Column("resolution_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("disputes", "resolution_notes")
