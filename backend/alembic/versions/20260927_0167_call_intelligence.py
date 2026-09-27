"""Call intelligence: batch jobs, model provenance on findings, turn signals (sql/71).

Revision ID: 20260927_0167
Revises: 20260927_0166
Create Date: 2026-09-27

Mirror: sql/71_call_intelligence.sql. Schema only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260927_0167"
down_revision: Union[str, None] = "20260927_0166"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "71_call_intelligence.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
