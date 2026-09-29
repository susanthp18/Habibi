"""Callback reminders are sent by the system, not declared sent (sql/80).

Revision ID: 20260929_0175
Revises: 20260929_0174
Mirror: sql/80_callback_reminder_dispatch.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260929_0175"
down_revision: Union[str, None] = "20260929_0174"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "80_callback_reminder_dispatch.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
