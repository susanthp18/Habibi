"""Global rows: writable in platform scope only, and their children with them.

Revision ID: 20260925_0158
Revises: 20260925_0157
Create Date: 2026-09-25

Mirror: sql/62_platform_write.sql for the new permission and its stock admin
grant. The policies are not mirrored, like 0126: they are derived by
``rls.plan``, so a fresh build picks them up from ``scripts/rls.py apply``.
Three changes, all in the derivation:

* A NULL-tenant row (statutory rule sets, the platform budget) is writable
  inside ``platform_scope.enter`` -- which requires ``perm-platform-write`` --
  and nowhere else. Submit/Approve on a statutory set were row-security 500s.
* Children of those tables (``policy_rules``, ``budget_rules``,
  ``budget_alert_events``) inherit the parent's *write* side. They copied its
  read side, so a tenant could add rules to a statutory set.
* The write predicate gates UPDATE and DELETE as well as INSERT, with a
  separate SELECT-only policy for the wider read side. A single FOR ALL
  policy let a tenant delete a statutory set it could not insert.
"""

from __future__ import annotations

import os
from typing import Sequence, Union

from pathlib import Path

from alembic import op
from replay import apply_sql
from sqlalchemy import text

revision: str = "20260925_0158"
down_revision: Union[str, None] = "20260925_0157"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "62_platform_write.sql"


def upgrade() -> None:
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
    raise NotImplementedError("forward-only; re-run scripts/rls.py apply from the older tree")
