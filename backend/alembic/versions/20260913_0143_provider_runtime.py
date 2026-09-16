"""The call host reports what it can construct; the API stops guessing (sql/51).

Revision ID: 20260913_0143
Revises: 20260913_0142
Create Date: 2026-09-13

Mirror: sql/51_provider_runtime.sql.

`provider_models.runtime` was computed on read by importing the service class
into the asking process. Only the voice image has Pipecat, so the API answered
for itself and reported every model `unavailable` while calls ran fine. These
columns give the voice runtime somewhere to publish the answer on its way up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql

revision: str = "20260913_0143"
down_revision: Union[str, None] = "20260913_0142"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "51_provider_runtime.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    for col in ("runtime", "runtime_detail", "runtime_checked_at"):
        op.execute(f"ALTER TABLE provider_models DROP COLUMN IF EXISTS {col}")
