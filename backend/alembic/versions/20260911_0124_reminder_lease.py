"""A reminder is sent after its claim commits: `promise_reminders.sending_at`.

Revision ID: 20260911_0124
Revises: 20260911_0123
Create Date: 2026-09-11

Mirror: sql/35_reminder_lease.sql. Catalog-only -- a nullable lease column and
a counter with a non-volatile default. No backfill.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260911_0124"
down_revision: Union[str, None] = "20260911_0123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "35_reminder_lease.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
