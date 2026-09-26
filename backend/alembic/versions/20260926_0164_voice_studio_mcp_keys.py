"""Per-user Voice Studio MCP authoring keys.

Revision ID: 20260926_0164
Revises: 20260926_0163
Mirror: sql/68_voice_studio_mcp_keys.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260926_0164"
down_revision: Union[str, None] = "20260926_0163"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "68_voice_studio_mcp_keys.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
