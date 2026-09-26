"""`websocket` transport on voice_sessions (sql/61).

Revision ID: 20260925_0157
Revises: 20260921_0156
Create Date: 2026-09-25

Mirror: sql/61_websocket_transport.sql. Widens a CHECK; touches no row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260925_0157"
down_revision: Union[str, None] = "20260921_0156"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "61_websocket_transport.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
