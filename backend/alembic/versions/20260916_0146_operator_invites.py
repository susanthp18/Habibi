"""Operator invites for Entra first-login (sql/55).

Revision ID: 20260916_0146
Revises: 20260916_0145
Create Date: 2026-09-16

Mirror: sql/55_operator_invites.sql. Do not apply against a live database
from an agent session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260916_0146"
down_revision: Union[str, None] = "20260916_0145"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "55_operator_invites.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
