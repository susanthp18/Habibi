"""Semantic product routing: kb_products and kb_product_utterances (sql/64).

Revision ID: 20260925_0160
Revises: 20260925_0159
Create Date: 2026-09-25

Mirror: sql/64_kb_products.sql. Both tables carry tenant_id, so this migration
installs and enables their derived row-security policies the way 0144 did for
promise_revisions. The rows themselves are generated from the indexed documents
by ``python scripts/kb_product_profiles.py`` (and on every ingest/reindex), not
seeded here: they are written by a model call, which a migration must not make.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql
from sqlalchemy import text

revision: str = "20260925_0160"
down_revision: Union[str, None] = "20260925_0159"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "64_kb_products.sql"


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
    op.execute("DROP TABLE IF EXISTS kb_product_utterances")
    op.execute("DROP TABLE IF EXISTS kb_products")
