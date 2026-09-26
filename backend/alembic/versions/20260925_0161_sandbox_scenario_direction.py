"""Seeded sandbox scenarios say they are outbound calls (sql/65).

Revision ID: 20260925_0161
Revises: 20260925_0160
Create Date: 2026-09-25

Mirror: sql/65_sandbox_scenario_direction.sql. Data only: adds
``direction``/``objective`` to the four seeded scenarios' ``sim_persona`` so
Sandbox Live rehearses them through the outbound door.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260925_0161"
down_revision: Union[str, None] = "20260925_0160"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "65_sandbox_scenario_direction.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
