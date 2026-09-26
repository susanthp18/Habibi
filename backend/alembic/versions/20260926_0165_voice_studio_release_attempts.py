"""Durable cross-service Voice Studio release intents (sql/69).

Revision ID: 20260926_0165
Revises: 20260926_0164
Mirror: sql/69_voice_studio_release_attempts.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260926_0165"
down_revision: Union[str, None] = "20260926_0164"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "69_voice_studio_release_attempts.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
