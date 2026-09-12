"""btree_gist, manifests unique per payload hash, the evaluation schema owned (sql/46).

Revision ID: 20260912_0136
Revises: 20260912_0135
Create Date: 2026-09-12

Mirror: sql/46_evaluation_ownership.sql -- the delta sql/24 and sql/00 gained
after their migrations shipped. The dev database already carried it by hand;
this is the step an upgraded database replays.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260912_0136"
down_revision: Union[str, None] = "20260912_0135"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "46_evaluation_ownership.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    # Ownership and the wider unique key are the controls; handing the
    # evaluation schema back to the app role is a widening no downgrade
    # should perform silently.
    raise RuntimeError("irreversible: evaluation schema ownership is a control, not a schema detail")
