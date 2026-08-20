"""Tenant-scope idempotency_keys — cross-tenant cached-response leak.

Revision ID: 20260812_0059
Revises: 20260801_0058
Create Date: 2026-08-12

``idempotency_keys`` stored a cached response body keyed by ``(endpoint, key)``
with no tenant column. The key is client-supplied, and clients routinely use
predictable ones ("order-123"), so two tenants posting the same key to the same
endpoint collide — and the second caller is served the **first tenant's cached
response body**, which contains that tenant's customer data.

That is a data-leak primitive rather than a scoping oversight: the replay path
returns the stored response verbatim without re-reading any row, so none of the
tenant predicates elsewhere in the data layer get a chance to filter it.

Latent today because the deployment is single-tenant, and cheap to close now —
which is the whole argument for doing it before the tenancy work rather than as
part of it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0059"
down_revision: Union[str, Sequence[str], None] = "20260801_0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable first, then backfill, then NOT NULL: adding a NOT NULL column to
    # a populated table needs a default, and a default read from the
    # environment would bake one deployment's tenant into the schema.
    op.add_column("idempotency_keys", sa.Column("tenant_id", sa.Text(), nullable=True))

    # Existing rows belong to whichever tenant this deployment has been serving.
    # Resolved from the tenants table rather than an env var so the migration is
    # reproducible: a single-tenant install has exactly one row, and anything
    # else means an operator must decide, so we fail loudly instead of guessing.
    op.execute(
        """
        DO $$
        DECLARE only_tenant TEXT;
        BEGIN
          IF EXISTS (SELECT 1 FROM idempotency_keys WHERE tenant_id IS NULL) THEN
            SELECT id INTO only_tenant FROM tenants LIMIT 2;
            IF (SELECT count(*) FROM tenants) <> 1 THEN
              RAISE EXCEPTION
                'idempotency_keys backfill needs exactly one tenant to attribute '
                'existing rows to; found %. Truncate the table (cached responses '
                'are disposable) or attribute the rows manually, then re-run.',
                (SELECT count(*) FROM tenants);
            END IF;
            UPDATE idempotency_keys SET tenant_id = only_tenant WHERE tenant_id IS NULL;
          END IF;
        END $$;
        """
    )

    op.alter_column("idempotency_keys", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_idempotency_keys_tenant",
        "idempotency_keys",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Tenant leads the key: it is the first predicate on every lookup, and it is
    # what makes two tenants' identical keys distinct rows rather than one.
    op.drop_constraint("idempotency_keys_pkey", "idempotency_keys", type_="primary")
    op.create_primary_key(
        "idempotency_keys_pkey", "idempotency_keys", ["tenant_id", "endpoint", "key"]
    )


def downgrade() -> None:
    # Collapsing back to (endpoint, key) can violate the narrower primary key
    # once more than one tenant has used the same key, so drop the rows first —
    # cached idempotent responses are disposable by construction, and a replay
    # after this simply re-executes the mutation.
    op.execute("DELETE FROM idempotency_keys")
    op.drop_constraint("idempotency_keys_pkey", "idempotency_keys", type_="primary")
    op.create_primary_key("idempotency_keys_pkey", "idempotency_keys", ["endpoint", "key"])
    op.drop_constraint("fk_idempotency_keys_tenant", "idempotency_keys", type_="foreignkey")
    op.drop_column("idempotency_keys", "tenant_id")
