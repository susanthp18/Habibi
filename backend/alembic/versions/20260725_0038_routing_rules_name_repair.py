"""Repair routing_rules.name NULLs before NOT NULL invariant.

Revision ID: 20260725_0038
Revises: 20260725_0037
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260725_0038"
down_revision: Union[str, Sequence[str], None] = "20260725_0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE routing_rules
        SET name = COALESCE(NULLIF(btrim(name), ''), id)
        WHERE name IS NULL OR btrim(coalesce(name, '')) = ''
        """
    )
    # Re-assert NOT NULL for environments that somehow lost the constraint.
    # Deliberately unguarded: swallowing the exception would hide remaining
    # NULLs, lock timeouts, permission failures and concurrent writes, leaving
    # the revision "applied" with the invariant absent.
    op.execute("ALTER TABLE routing_rules ALTER COLUMN name SET NOT NULL")


def downgrade() -> None:
    # The backfill itself is irreversible (the pre-migration NULLs are gone),
    # but the schema change is not: leaving NOT NULL in place meant a rolled
    # back app version that inserts a routing rule without `name` failed, so
    # the downgrade did not actually restore the previous contract.
    op.execute("ALTER TABLE routing_rules ALTER COLUMN name DROP NOT NULL")
