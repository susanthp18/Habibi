"""Grant new agent/eval permissions to stock roles.

Revision ID: 20260815_0074
Revises: 20260815_0073
Create Date: 2026-08-15

Phase 1 added agent.edit / agent.publish / eval.run / redteam.run to
PERMISSION_CATALOG. Admin's ROLE_DEFAULTS is ALL_PERMISSIONS, so the stock
admin role must receive the new rows or the grants table silently lags the
catalog — the same class of lockout 0064 fixed.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260815_0074"
down_revision: Union[str, Sequence[str], None] = "20260815_0073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STOCK_ROLES: dict[str, str] = {
    "role-agent": "agent",
    "role-supervisor": "supervisor",
    "role-admin": "admin",
    "role-qa": "qa_reviewer",
}


def upgrade() -> None:
    import authz

    conn = op.get_bind()
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
            continue
        for permission_id in sorted(authz.ROLE_DEFAULTS.get(role_key, ())):
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id)"
                    " VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


def downgrade() -> None:
    pass
