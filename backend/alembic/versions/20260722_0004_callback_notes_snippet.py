"""callback outcome notes + transcript

Persists CRM outcome notes and the capture snippet collected on the Callbacks
screen. Previously the UI gathered both and had nowhere to store them.

Revision ID: 20260722_0004
Revises: 20260722_0003
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0004"
down_revision: Union[str, Sequence[str], None] = "20260722_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("callbacks", sa.Column("transcript_snippet", sa.Text(), nullable=True))
    op.add_column("callbacks", sa.Column("outcome_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("callbacks", "outcome_notes")
    op.drop_column("callbacks", "transcript_snippet")
