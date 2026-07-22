"""baseline current Postgres schema

Revision ID: 20260721_0001
Revises:
Create Date: 2026-07-21

The current enterprise schema is authored in backend/sql/*.sql and has already
been applied to collections_db. This baseline revision intentionally stamps
that known-good state so subsequent schema changes are tracked by Alembic.
"""

from typing import Sequence, Union


revision: str = "20260721_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

