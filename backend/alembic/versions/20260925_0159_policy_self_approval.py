"""Break-glass self-approval of a rule set, reason on the row (sql/63).

Revision ID: 20260925_0159
Revises: 20260925_0158
Create Date: 2026-09-25

Mirror: sql/63_policy_self_approval.sql. Adds a nullable column and widens a
CHECK so approver = submitter is legal only with a stored reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260925_0159"
down_revision: Union[str, None] = "20260925_0158"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "63_policy_self_approval.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
