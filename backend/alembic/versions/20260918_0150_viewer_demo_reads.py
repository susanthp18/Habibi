"""Viewer demo-book read grants (sql/54).

Revision ID: 20260918_0150
Revises: 20260916_0146
Create Date: 2026-09-18

Mirror: sql/54_viewer_demo_reads.sql. Do not apply against a live database
from an agent session; the orchestrator runs upgrade after review.

Untracked 0147–0149 (access-requests / campaign / telephony) also revise
0146 in the mixed tree; rebase those onto this revision before they land.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260918_0150"
down_revision: Union[str, None] = "20260916_0146"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "54_viewer_demo_reads.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
