"""mcp_connectors.health admits 'blocked' (sql/45).

Revision ID: 20260912_0135
Revises: 20260912_0134
Create Date: 2026-09-12

Mirror: sql/45_connector_health_blocked.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql

revision: str = "20260912_0135"
down_revision: Union[str, None] = "20260912_0134"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "45_connector_health_blocked.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    op.execute("UPDATE mcp_connectors SET health = 'down' WHERE health = 'blocked'")
    op.execute("ALTER TABLE mcp_connectors DROP CONSTRAINT IF EXISTS mcp_connectors_health_check")
    op.execute(
        "ALTER TABLE mcp_connectors ADD CONSTRAINT mcp_connectors_health_check "
        "CHECK (health IN ('unknown','healthy','degraded','down'))"
    )
