"""Root the orphaned configuration tables in a tenant.

Revision ID: 20260812_0060
Revises: 20260812_0059
Create Date: 2026-08-12

The tenancy survey walked the foreign-key graph and classified every table by
its shortest hop count to a tenant-rooted one. Most of the schema is fine:
25 tables carry ``tenant_id`` already and 53 more are a single indexed hop from
one, so row-level security can reach them with an ``EXISTS`` against the parent
and needs no column here at all.

24 tables had *no path to a tenant whatsoever*. Ten of those are genuinely
global — ``tenants`` itself, the permission catalog, webhook event types, the
Azure voice catalog, alembic's own bookkeeping. The rest hold per-tenant
business configuration and simply lost their tenant: a bank's product catalog,
its QA rubric, its compliance rules, its document templates.

Those are the ones RLS cannot be written for, because there is nothing to write
a policy against.

Only the cluster *roots* need a column. ``qa_rubric_sections`` and
``qa_rubric_criteria`` hang off ``qa_rubrics``; ``product_eligibility_rules``
and ``product_relations`` hang off ``products``. Rooting the parent turns each
child into a one-hop table, which the same ``EXISTS`` policy covers. Nine
columns therefore resolve thirteen orphans.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0060"
down_revision: Union[str, Sequence[str], None] = "20260812_0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Cluster roots only — see the module docstring for why the children are not here.
TABLES: tuple[str, ...] = (
    "compliance_rules",
    "qa_rubrics",
    "products",
    "document_templates",
    "persona_presets",
    "sandbox_scenarios",
    "kb_snapshots",
    "tts_voices",
    "voice_sandbox_sessions",
)


def _backfill(table: str) -> str:
    """Attribute existing rows, refusing to guess when it is ambiguous.

    A default read from the environment would bake one deployment's tenant into
    the schema, and picking an arbitrary tenant on a multi-tenant install would
    silently hand one customer's configuration to another. A single-tenant
    install has exactly one answer; anything else is an operator decision.
    """
    return f"""
        DO $$
        DECLARE only_tenant TEXT;
        BEGIN
          IF EXISTS (SELECT 1 FROM {table} WHERE tenant_id IS NULL) THEN
            IF (SELECT count(*) FROM tenants) <> 1 THEN
              RAISE EXCEPTION
                'cannot attribute existing {table} rows: expected exactly one '
                'tenant, found %. Assign {table}.tenant_id manually, then re-run.',
                (SELECT count(*) FROM tenants);
            END IF;
            SELECT id INTO only_tenant FROM tenants;
            UPDATE {table} SET tenant_id = only_tenant WHERE tenant_id IS NULL;
          END IF;
        END $$;
    """


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.Text(), nullable=True))
        op.execute(_backfill(table))
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant", table, "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        # Leading-column index: every RLS policy and every scoped read filters on
        # this first, and without it each one degrades to a sequential scan.
        op.create_index(f"idx_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"idx_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
