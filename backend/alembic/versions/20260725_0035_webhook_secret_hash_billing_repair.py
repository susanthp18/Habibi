"""webhook_endpoints.secret_hash + billing July invoice repair.

Revision ID: 20260725_0035
Revises: 20260724_0034
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled

revision: str = "20260725_0035"
down_revision: Union[str, Sequence[str], None] = "20260724_0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_HASH_HEADER = "X-Webhook-Secret-SHA256"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE webhook_endpoints ADD COLUMN IF NOT EXISTS secret_hash TEXT"
    )
    # Promote any legacy demo header hashes into the column, then scrub headers.
    op.execute(
        f"""
        UPDATE webhook_endpoints we
        SET secret_hash = h.header_value
        FROM webhook_endpoint_headers h
        WHERE h.endpoint_id = we.id
          AND h.header_key = '{_LEGACY_HASH_HEADER}'
          AND (we.secret_hash IS NULL OR we.secret_hash = '')
        """
    )
    op.execute(
        """
        DELETE FROM webhook_endpoint_headers
        WHERE header_key IN ('X-Webhook-Secret-SHA256', 'X-Webhook-Secret')
        """
    )

    # Demo-only repair: create the July 2026 draft invoice for the demo tenant
    # when it is missing. Gated on seed_demo_enabled() and on the tenant
    # actually existing — a tenant-specific data insert has no business running
    # unconditionally in every environment's migration path, and 'INV-2026-07'
    # would otherwise appear in production databases that never had that data.
    if not seed_demo_enabled():
        return
    op.execute(
        """
        INSERT INTO invoices (
          id, tenant_id, invoice_month, environment, total_inr, status, issued_at
        )
        SELECT
          'INV-2026-07', 'hdfc.retail', '2026-07', 'production', 0, 'draft',
          -- Issue date is the start of the month, not a future date: a draft
          -- stamped 2026-08-01 sorted ahead of real invoices and read as
          -- already issued.
          DATE '2026-07-01'
        WHERE EXISTS (SELECT 1 FROM tenants WHERE id = 'hdfc.retail')
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Restore the legacy header from secret_hash before dropping the column,
    # so the prior application version — which authenticated webhooks off that
    # header — keeps working after a rollback.
    op.execute(
        f"""
        INSERT INTO webhook_endpoint_headers (id, endpoint_id, header_key, header_value)
        SELECT 'weh-' || we.id || '-secret-sha256', we.id,
               '{_LEGACY_HASH_HEADER}', we.secret_hash
        FROM webhook_endpoints we
        WHERE we.secret_hash IS NOT NULL AND we.secret_hash <> ''
          AND NOT EXISTS (
            SELECT 1 FROM webhook_endpoint_headers h
            WHERE h.endpoint_id = we.id AND h.header_key = '{_LEGACY_HASH_HEADER}'
          )
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute("ALTER TABLE webhook_endpoints DROP COLUMN IF EXISTS secret_hash")
