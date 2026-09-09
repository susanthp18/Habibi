"""W8a engine_config: the cost book is a row, and config_version names it.

Revision ID: 20260909_0116
Revises: 20260909_0115
Create Date: 2026-09-09

NOT applied to the running database by this work package. Mirror:
sql/27_engine_config.sql.

No backfill. `engine_config` starts empty on purpose: the resolver layers
tenant and portfolio rows over the environment, so an empty table is exactly
today's behaviour and `config_version()` keeps returning the W2 'env:<sha>'
until somebody writes the first row. Measured read-only on collections
(2026-09-09, alembic 20260909_0115): 302 treatment_decisions rows, all
carrying config_version='env:...', none resolvable -- which is the gap W8's
exit criterion closes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260909_0116"
down_revision: Union[str, None] = "20260909_0115"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "27_engine_config.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
