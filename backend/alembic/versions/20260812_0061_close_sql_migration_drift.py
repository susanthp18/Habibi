"""Close the columns sql/*.sql declares that no migration ever created.

Revision ID: 20260812_0061
Revises: 20260812_0060
Create Date: 2026-08-12

This repository keeps two sources of schema truth — ``sql/*.sql`` is the
authoritative current shape, and ``alembic/versions/`` carries deltas for
databases that already exist — and nothing checked that they agreed.
``tests/test_schema_parity.py`` now does, and it found drift in both directions.

The other direction (``prompt_versions.tuning``, present in migrated databases
and missing from ``sql/``) is fixed in ``sql/`` itself, since that file is
simply behind.

This revision fixes the dangerous direction. These three columns are declared in
``sql/`` and created by no migration, so every *existing* deployment is missing
them while every fresh one has them. That asymmetry cannot be found by running
the app against a fresh database, which is exactly what a developer does — it
only shows up in production.

Definitions mirror ``sql/07_compliance_qa.sql`` exactly, defaults included, so
the two sources converge rather than drift further.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260812_0061"
down_revision: Union[str, Sequence[str], None] = "20260812_0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS throughout: a database built from sql/*.sql already has
    # these, and this revision must be a no-op there rather than an error.
    op.execute("ALTER TABLE calibration_sessions ADD COLUMN IF NOT EXISTS name TEXT")
    op.execute(
        "ALTER TABLE calibration_sessions "
        "ADD COLUMN IF NOT EXISTS target_scores jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE coaching_actions "
        "ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'General'"
    )


def downgrade() -> None:
    op.drop_column("coaching_actions", "category")
    op.drop_column("calibration_sessions", "target_scores")
    op.drop_column("calibration_sessions", "name")
