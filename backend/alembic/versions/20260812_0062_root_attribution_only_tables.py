"""Give a tenant to the tables whose only path to one was an audit column.

Revision ID: 20260812_0062
Revises: 20260812_0061
Create Date: 2026-08-12

Migration 20260812_0060 closed the tables with *no* foreign-key path to a
tenant. Deriving row-level-security policies from that same graph
(``backend/rls.py``) showed the survey had been too generous: it counted any
foreign key as a path to a tenant, and some of those keys do not mean what a
tenancy path has to mean.

A foreign key can say two different things. ``dispute_evidence.dispute_id`` says
which dispute the evidence *belongs to* — remove the dispute and the evidence
has no reason to exist. ``kb_documents.updated_by_user_id`` says only who last
edited the document. Both are edges in the graph; only the first carries
ownership.

For these four tables the attribution column was the *only* edge, so the derived
policy came out as "this document belongs to whichever tenant employs the person
who last touched it". Three things are wrong with that:

* **It hides most of the data.** 20 of 21 ``kb_documents`` rows have a NULL
  editor, and the KB cluster hanging off them — ``faq_pairs``, ``kb_chunks``,
  ``kb_index_jobs`` — inherits the problem. 654 rows in the development
  database belong to no tenant under that rule and would be invisible to
  everyone, which is the entire knowledge base.
* **It is destructible.** Every one of these columns is ``ON DELETE SET NULL``.
  Deleting a user would not merely lose attribution; it would silently move
  that user's documents out of the tenant and out of every query.
* **It is simply not what the column means.** A prompt version's tenant is the
  bank it was written for, not the current employer of its author.

``retrieval_logs`` is here for the first reason on its own: all three of its
links are optional, and 127 of 214 rows have none of them set.

Operational note for a large install: ``ADD COLUMN`` without a default is
instant, but the backfill ``UPDATE`` rewrites every row and ``SET NOT NULL``
scans the table, both under an ACCESS EXCLUSIVE lock. ``retrieval_logs`` is
append-only telemetry and is the one table here that grows without bound — on a
big deployment, do it in a maintenance window.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0062"
down_revision: Union[str, Sequence[str], None] = "20260812_0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Tables whose only foreign key out was an ``ON DELETE SET NULL`` audit column.
TABLES: tuple[str, ...] = (
    "kb_documents",
    "prompt_versions",
    "export_jobs",
    "retrieval_logs",
)


def _backfill(table: str) -> str:
    """Attribute existing rows, refusing to guess when it is ambiguous.

    Identical rule to 20260812_0060: a single-tenant install has exactly one
    answer, and anything else is an operator decision rather than a default this
    migration is entitled to pick.
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

    _scope_natural_keys_to_tenant()


def _scope_natural_keys_to_tenant() -> None:
    """Uniqueness on a business key has to include the tenant.

    Surveying unique indexes after rooting these tables turned up two that
    constrain a *natural* key globally. Both are silent until a second tenant
    exists, and then they fail as a confusing insert error rather than anything
    that names tenancy as the cause. (Primary keys on ``id`` are fine as they
    are: those are surrogate ids, and global uniqueness is strictly stronger
    than per-tenant uniqueness.)

    ``compliance_rules.code`` is a regulator's rule code. Two banks referencing
    the same regulation both need the row; only the first could have it.

    ``ux_prompt_versions_one_published`` enforces "at most one published prompt
    version" as a partial unique index on a constant-ish column. That was right
    when the table had no tenant. With one, it means at most one published
    prompt version *in the entire installation* — the second tenant to publish
    would be rejected because the first had already published.
    """
    op.drop_constraint("compliance_rules_code_key", "compliance_rules", type_="unique")
    op.create_unique_constraint(
        "ux_compliance_rules_tenant_code", "compliance_rules", ["tenant_id", "code"]
    )

    op.drop_index("ux_prompt_versions_one_published", table_name="prompt_versions")
    op.execute(
        "CREATE UNIQUE INDEX ux_prompt_versions_one_published "
        "ON prompt_versions (tenant_id) WHERE status = 'published'"
    )


def downgrade() -> None:
    op.drop_index("ux_prompt_versions_one_published", table_name="prompt_versions")
    op.drop_constraint("ux_compliance_rules_tenant_code", "compliance_rules", type_="unique")
    op.create_unique_constraint("compliance_rules_code_key", "compliance_rules", ["code"])

    for table in reversed(TABLES):
        op.drop_index(f"idx_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    # Recreated last: it references no column this migration drops, but it must
    # not exist while prompt_versions still has the tenant-scoped version.
    op.execute(
        "CREATE UNIQUE INDEX ux_prompt_versions_one_published "
        "ON prompt_versions ((status)) WHERE status = 'published'"
    )
