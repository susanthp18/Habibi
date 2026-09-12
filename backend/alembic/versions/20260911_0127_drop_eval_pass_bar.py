"""Drop `eval_tasks.pass_bar`: written 'all' everywhere, read nowhere.

Revision ID: 20260911_0127
Revises: 20260911_0126
Create Date: 2026-09-11

Mirror: sql/37_drop_eval_pass_bar.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260911_0127"
down_revision: Union[str, None] = "20260911_0126"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "37_drop_eval_pass_bar.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
