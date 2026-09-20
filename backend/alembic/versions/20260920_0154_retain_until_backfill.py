"""Backfill retain_until on rows written before the stamp.

Revision ID: 20260920_0154
Revises: 20260920_0153
Create Date: 2026-09-20

NULL retain_until is a bug, not forever: the reaper deletes only
``retain_until <= now()``. Stamp the four tables in sql/28_retention.sql
via ``retention.backfill`` (anchor + policy days). Do not apply against a
live database from an agent session; the orchestrator runs upgrade after
review.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260920_0154"
down_revision: Union[str, None] = "20260920_0153"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from agent_core import retention

    conn = op.get_bind()
    tenants = [str(row[0]) for row in conn.execute(text("SELECT id FROM tenants"))]
    for tenant_id in tenants:
        for kind in retention.DEFAULTS:
            retention.backfill(conn, tenant_id=tenant_id, record_kind=kind)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
