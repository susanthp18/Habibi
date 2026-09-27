"""Tamper-evident call evidence: per-tenant hash chain (sql/73).

Revision ID: 20260927_0169
Revises: 20260927_0168
Create Date: 2026-09-27

Mirror: sql/73_evidence_chain.sql. Schema only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260927_0169"
down_revision: Union[str, None] = "20260927_0168"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "73_evidence_chain.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
