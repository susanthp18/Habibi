"""Operator access requests (sql/56).

Revision ID: 20260916_0147
Revises: 20260920_0154
Create Date: 2026-09-16

Mirror: sql/56_operator_access_requests.sql. Do not apply against a live
database from an agent session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260916_0147"
down_revision: Union[str, None] = "20260920_0154"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "56_operator_access_requests.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
