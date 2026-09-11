"""Row-level security: install the derived policies and turn them on.

Revision ID: 20260911_0126
Revises: 20260911_0125
Create Date: 2026-09-11

Not a SQL mirror: the policies are *derived* from the foreign-key graph by
``rls.plan`` at the moment this runs (222 on 2026-09-11), so the fresh-build
equivalent is the tool, not a file --
``python scripts/rls.py apply && python scripts/rls.py enable --verify-as
collections_app`` after the schema is applied. The docker-compose header
says so.

What ``enable`` does, and why it can run in a migration: it counts the rows
that belong to this tenant, turns policies on for every covered table, counts
again *as the application role* inside the same transaction, and raises if
the two disagree -- and Postgres keeps DDL transactional, so a refused enable
leaves nothing behind. A superuser ignores policies, so the application must
connect as the provisioned role (``APP_DB_USER`` in compose) for any of this
to constrain a query; this migration verifies as that role when it exists and
says so loudly when it does not.

Reversal: ``python scripts/rls.py disable`` -- policies stay installed and
inert. Or point DATABASE_URL back at the owner, which bypasses them.
"""

from __future__ import annotations

import logging
import os
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260911_0126"
down_revision: Union[str, None] = "20260911_0125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

#: The role compose points the application at. Override with APP_DB_USER.
_APP_ROLE = (os.getenv("APP_DB_USER") or "collections_app").strip()


def upgrade() -> None:
    import rls
    import tenant_context

    conn = op.get_bind()
    # `enable` refuses when the tenant GUC is unset (every policy would match
    # nothing). Alembic's connection did not start with it; bind the migrating
    # tenant for this transaction, exactly as db_core does per request.
    conn.execute(
        text(f"SET LOCAL {tenant_context.GUC} = '{tenant_context.validate(tenant_context.current_tenant())}'")
    )
    rls.apply(conn)
    role_exists = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}
    ).scalar()
    if role_exists:
        result = rls.enable(conn, verify_as=_APP_ROLE)
        logger.info(
            "row-level security enabled on %s tables, verified as %r (%s rows)",
            result["tables"],
            result["verified_as"],
            result["verified_rows"],
        )
        return
    # No application role yet: the policies are installed and switched on for
    # a role that does not exist. Nothing changes for the owner, which
    # bypasses them; the day `provision-role` runs and DATABASE_URL moves,
    # they apply. Said out loud rather than silently skipped.
    result = rls.enable(conn, allow_bypassing_role=True)
    logger.warning(
        "row-level security enabled on %s tables but role %r does not exist -- "
        "the application still connects as the owner and bypasses every policy. "
        "Run: python scripts/rls.py provision-role %s --password ...",
        result["tables"],
        _APP_ROLE,
        _APP_ROLE,
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only; `python scripts/rls.py disable` turns it off")
