"""MCP tasks are a queue; nightly jobs run once (sql/50).

Revision ID: 20260913_0142
Revises: 20260912_0141
Create Date: 2026-09-13

Mirror: sql/50_queues_once.sql. nightly_runs is the first tenant-rooted table
created after 0126 turned row security on, so this migration installs and
enables its derived policy the way 0126 did for the rest -- the sql/ build
gets the same from ``scripts/rls.py apply && enable`` after the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql
from sqlalchemy import text

revision: str = "20260913_0142"
down_revision: Union[str, None] = "20260912_0141"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "50_queues_once.sql"


def upgrade() -> None:
    import os

    import rls
    import tenant_context

    apply_sql(_SQL)
    conn = op.get_bind()
    conn.execute(
        text(f"SET LOCAL {tenant_context.GUC} = '{tenant_context.validate(tenant_context.current_tenant())}'")
    )
    rls.apply(conn)
    app_role = (os.getenv("APP_DB_USER") or "collections_app").strip()
    role_exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": app_role}).scalar()
    if role_exists:
        rls.enable(conn, verify_as=app_role)
    else:
        rls.enable(conn, allow_bypassing_role=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS nightly_runs")
    op.execute("DROP INDEX IF EXISTS idx_mcp_tasks_queue")
    op.execute("ALTER TABLE mcp_tasks DROP CONSTRAINT IF EXISTS mcp_tasks_status_check")
    op.execute(
        "ALTER TABLE mcp_tasks ADD CONSTRAINT mcp_tasks_status_check "
        "CHECK (status IN ('queued','running','succeeded','failed'))"
    )
    for col in ("attempt", "locked_at", "locked_by", "run_after"):
        op.execute(f"ALTER TABLE mcp_tasks DROP COLUMN IF EXISTS {col}")
