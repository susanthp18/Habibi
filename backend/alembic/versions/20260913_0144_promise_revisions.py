"""One open promise per account, renegotiable with a history (sql/52).

Revision ID: 20260913_0144
Revises: 20260913_0143
Create Date: 2026-09-13

Mirror: sql/52_promise_revisions.sql. promise_revisions is a new
customer-reaching table, so this migration installs and enables its derived
row-security policy the way 0142 did for nightly_runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql
from sqlalchemy import text

revision: str = "20260913_0144"
down_revision: Union[str, None] = "20260913_0143"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "52_promise_revisions.sql"


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
    op.execute("DROP TABLE IF EXISTS promise_revisions")
    op.execute("DROP INDEX IF EXISTS uq_promises_one_open")
    op.execute("DROP INDEX IF EXISTS idx_routing_rule_executions_rule_evaluated")
    op.execute("ALTER TABLE promise_reminders DROP COLUMN IF EXISTS last_error")
    op.execute("UPDATE promises SET status = 'broken' WHERE status = 'cancelled'")
    op.execute("ALTER TABLE promises DROP CONSTRAINT IF EXISTS promises_status_check")
    op.execute(
        "ALTER TABLE promises ADD CONSTRAINT promises_status_check "
        "CHECK (status IN ('upcoming','due_today','kept','broken','partial'))"
    )
    for col in ("revision_count", "cancel_reason", "cancelled_at", "cancelled_by"):
        op.execute(f"ALTER TABLE promises DROP COLUMN IF EXISTS {col}")
