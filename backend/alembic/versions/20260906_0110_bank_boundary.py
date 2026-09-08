"""W5 bank boundary: contracts, manifests, outbox, mappings, evaluation schema.

Revision ID: 20260906_0110
Revises: 20260906_0109
Create Date: 2026-09-06

NOT applied to the running database by this work package. Mirror:
sql/24_bank_boundary.sql, sql/05_collections.sql (mandate status +
enactment_attempts contract columns).

Measured on collections (2026-09-06, alembic 20260905_0106):
  bank_contracts=absent, action_contracts=absent,
  evaluation.protected_attributes=absent, public bank_* tables=0.
  No backfill — there is nothing to relabel as bank-reconciled evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260906_0110"
down_revision: Union[str, None] = "20260906_0109"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "24_bank_boundary.sql"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE enactment_attempts
          ADD COLUMN IF NOT EXISTS action_contract_id TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE enactment_attempts
          ADD COLUMN IF NOT EXISTS action_contract_digest TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE mandate_presentations
          DROP CONSTRAINT IF EXISTS mandate_presentations_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE mandate_presentations
          ADD CONSTRAINT mandate_presentations_status_check
          CHECK (status IN (
            'scheduled','submitted','awaiting_settlement',
            'success','returned','cancelled'
          )) NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE mandate_presentations VALIDATE CONSTRAINT mandate_presentations_status_check"
    )
    op.execute(
        """
        ALTER TABLE mandate_presentations
          DROP CONSTRAINT IF EXISTS ck_mandate_presentations_no_abandon
        """
    )
    op.execute(
        """
        ALTER TABLE mandate_presentations
          ADD CONSTRAINT ck_mandate_presentations_no_abandon
          CHECK (status <> 'abandoned') NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE mandate_presentations VALIDATE CONSTRAINT ck_mandate_presentations_no_abandon"
    )

    sql = _SQL.read_text(encoding="utf-8")
    conn = op.get_bind()
    conn.exec_driver_sql(sql)

    import authz

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
    stock = {
        "role-agent": "agent",
        "role-supervisor": "supervisor",
        "role-admin": "admin",
        "role-qa": "qa_reviewer",
    }
    for role_id, role_key in stock.items():
        for permission_id in sorted(authz.ROLE_DEFAULTS.get(role_key, ())):
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id)"
                    " SELECT :rid, :pid"
                    " WHERE EXISTS (SELECT 1 FROM roles WHERE id = :rid)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"rid": role_id, "pid": permission_id},
            )


def downgrade() -> None:
    raise NotImplementedError("forward-only")
