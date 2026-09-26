"""Demo book for the outbound handset (sql/60).

Revision ID: 20260921_0156
Revises: 20260921_0155
Create Date: 2026-09-21

Mirror: sql/60_demo_handset_book.sql. Idempotent inserts. Does not dial
and does not queue a message. Do not apply against a live database from
an agent session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260921_0156"
down_revision: Union[str, None] = "20260921_0155"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "60_demo_handset_book.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
