"""Give the stock roles the permissions they are supposed to have.

Revision ID: 20260812_0064
Revises: 20260812_0063
Create Date: 2026-08-12

``authz`` resolves a role's grants from ``role_permissions`` and treats what it
finds there as **authoritative** — that is what makes revoking a permission
work. A role with no rows at all falls back to a built-in default set, so a
fresh database is usable rather than locked out.

The demo seed predates that resolver and wrote six token grants across four
roles: Agent got two, Supervisor got ``qa-review`` and ``workqueue-write``, QA
Reviewer got one. Under the resolver those six are not a partial seed, they are
a complete and deliberate-looking policy, and they *replace* the defaults.

Nothing read the table until pass 1, so nothing noticed. With enforcement on —
which is the production default, since it follows authentication being
configured — every non-admin role loses almost all of its screens. Admin escapes
only through the separate ``'admin' in role_names`` superuser shortcut. Verified
by asking, rather than reasoning: a Supervisor hitting ``/customers``,
``/promises``, ``/callbacks`` and ``/calls`` got four 403s.

This tops the four stock roles up to their built-in defaults, **by id**. Roles
an operator created are not touched: for those, a missing grant is a decision,
and this migration has no way to tell a decision from an omission. For these
four the omission is documented in the seeder's own history.

Additive only — it grants, never revokes — so a stock role that has been
*extended* keeps everything it was given.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260812_0064"
down_revision: Union[str, Sequence[str], None] = "20260812_0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: ``role id -> the ROLE_DEFAULTS key its name normalises to``. Keyed on id, not
#: name, so renaming a stock role in the UI does not turn a custom role into a
#: target for this backfill.
STOCK_ROLES: dict[str, str] = {
    "role-agent": "agent",
    "role-supervisor": "supervisor",
    "role-admin": "admin",
    "role-qa": "qa_reviewer",
}


def upgrade() -> None:
    # Imported inside the function: alembic loads every revision module at
    # startup, and importing the application package at import time would make
    # the whole migration chain depend on it being importable.
    import authz

    conn = op.get_bind()
    from sqlalchemy import text

    # The catalog has to exist before anything can reference it — role_permissions
    # has a foreign key to permissions, and the old seed inserted 5 of 28 rows.
    for permission_id, module, action, description in authz.PERMISSION_CATALOG:
        conn.execute(
            text(
                "INSERT INTO permissions (id, module, action, description)"
                " VALUES (:id, :module, :action, :description)"
                " ON CONFLICT (id) DO UPDATE SET module = EXCLUDED.module,"
                " action = EXCLUDED.action, description = EXCLUDED.description"
            ),
            {
                "id": permission_id,
                "module": module,
                "action": action,
                "description": description,
            },
        )

    for role_id, role_key in STOCK_ROLES.items():
        exists = conn.execute(
            text("SELECT 1 FROM roles WHERE id = :id"), {"id": role_id}
        ).fetchone()
        if not exists:
            continue  # deployment never ran the demo seed
        for permission_id in sorted(authz.ROLE_DEFAULTS.get(role_key, ())):
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id)"
                    " VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


def downgrade() -> None:
    # Deliberately not reverting the grants. The previous state was six rows
    # that locked every non-admin out of the product; restoring it would be
    # restoring the bug, and a downgrade that re-breaks authorization is worse
    # than one that leaves a role holding a permission it does not need.
    pass
