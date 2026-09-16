"""Entra oid on users and the Viewer role (sql/53).

Revision ID: 20260916_0145
Revises: 20260913_0144
Create Date: 2026-09-16

Mirror: sql/53_entra_identity.sql. Do not apply against a live database
from an agent session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260916_0145"
down_revision: Union[str, None] = "20260913_0144"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "53_entra_identity.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
