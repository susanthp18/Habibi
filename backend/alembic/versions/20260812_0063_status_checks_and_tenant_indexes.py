"""Add the status CHECKs that only fresh databases had.

Revision ID: 20260812_0063
Revises: 20260812_0062
Create Date: 2026-08-12

``tests/test_schema_parity.py`` compared columns only. Extending it to indexes
and constraints — after having to check those by hand while reviewing 0062 —
found three more differences of the dangerous kind, where ``sql/*.sql`` declares
something no migration creates. Fresh databases have it, every existing
deployment does not, and a developer running against a fresh database cannot
see the difference.

Two are status vocabularies. ``calibration_sessions.status`` and
``coaching_actions.status`` are constrained to their allowed values in ``sql/``
and unconstrained everywhere else, so a typo or a stale client could write a
status the readers do not handle, and only in production.

The third — ``offer_decisions``' two CHECKs, which differ in name and, for
``response``, in text — is fixed in ``sql/`` instead: existing deployments have
the migration's version, so ``sql/`` is the copy that is behind.

Added NOT VALID and then validated. The two steps take a weaker lock than a
plain ``ADD CONSTRAINT``, which holds ACCESS EXCLUSIVE for a full table scan.
Both tables are small today; the pattern costs nothing here and is the one that
stays safe when they are not.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260812_0063"
down_revision: Union[str, Sequence[str], None] = "20260812_0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: ``(table, constraint, expression)`` — spelled exactly as ``sql/07_compliance_qa.sql``
#: declares them, so the two sources converge rather than drift again.
CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "calibration_sessions",
        "ck_calibration_sessions_status",
        "status IN ('active','closed')",
    ),
    (
        "coaching_actions",
        "ck_coaching_actions_status",
        "status IN ('assigned','in_progress','done')",
    ),
)


def upgrade() -> None:
    for table, name, expression in CHECKS:
        # IF NOT EXISTS has no ADD CONSTRAINT form, and a database built from
        # sql/*.sql already carries these — so ask the catalog first rather than
        # failing on the install where the constraint is already correct.
        op.execute(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}'
              ) THEN
                ALTER TABLE {table}
                  ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID;
                ALTER TABLE {table} VALIDATE CONSTRAINT {name};
              END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
