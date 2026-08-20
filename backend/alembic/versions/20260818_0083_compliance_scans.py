"""compliance_scans — the ledger of what the rule catalog has judged.

Revision ID: 20260818_0083
Revises: 20260817_0082
Create Date: 2026-08-18

Mirrors sql/07_compliance_qa.sql. SQL is inlined so alembic does not depend on
a sibling Path read at upgrade time.

Compliance detection used to happen once, live, inside a bot voice call. There
was no record of *what had been evaluated*, so three questions had no answer:
which interactions were ever checked, which rules are actually being looked for,
and what happens to history when a rule changes. Storing the rules version per
interaction turns the third one into a backfill instead of a fresh start.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260818_0083"
down_revision: Union[str, Sequence[str], None] = "20260817_0082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_scans (
          interaction_id TEXT PRIMARY KEY
            REFERENCES interactions(id) ON DELETE CASCADE,
          tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          rules_version  INTEGER NOT NULL,
          findings       INTEGER NOT NULL DEFAULT 0,
          scanned_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # The sweep's hot predicate: "not judged at the current rules version".
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_scans_version"
        " ON compliance_scans (rules_version, scanned_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_scans_tenant"
        " ON compliance_scans (tenant_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_compliance_scans_tenant")
    op.execute("DROP INDEX IF EXISTS idx_compliance_scans_version")
    op.execute("DROP TABLE IF EXISTS compliance_scans")
