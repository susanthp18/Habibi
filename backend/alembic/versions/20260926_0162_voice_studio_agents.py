"""Outbound objective -> PayInt Voice Studio agent bindings (sql/66).

Revision ID: 20260926_0162
Revises: 20260925_0161
Create Date: 2026-09-26

Mirror: sql/66_voice_studio_agents.sql. Schema only: one row per tenant and
objective ('*' = default) naming the engine agent and its API trigger path,
voice_studio_guardrails (PayInt's guardrails per engine agent) and
voice_studio_checks (scripted rehearsals, graded).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260926_0162"
down_revision: Union[str, None] = "20260925_0161"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "66_voice_studio_agents.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
