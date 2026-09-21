"""export_jobs.kind — dashboard CSVs without redaction ids.

Revision ID: 20260921_0155
Revises: 20260917_0149
Create Date: 2026-09-21

Mirror: sql/59_export_jobs_kind.sql. Do not apply against a live
database from an agent session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260921_0155"
down_revision: Union[str, None] = "20260917_0149"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "59_export_jobs_kind.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
