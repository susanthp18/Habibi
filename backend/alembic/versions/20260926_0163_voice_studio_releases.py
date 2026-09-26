"""Voice Studio release history: publish and rollback changelog (sql/67).

Revision ID: 20260926_0163
Revises: 20260926_0162
Create Date: 2026-09-26

Mirror: sql/67_voice_studio_releases.sql. Schema only: one row per publish or
rollback of an engine agent, with the actor and the changelog note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260926_0163"
down_revision: Union[str, None] = "20260926_0162"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "67_voice_studio_releases.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
