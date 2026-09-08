"""Executable contract: compiled bundle, deployment hash, A2A bot scope.

Revision ID: 20260906_0111
Revises: 20260906_0110
Create Date: 2026-09-06

NOT applied to the running database by this work package. Mirror:
sql/09_bot_config.sql (prompt_versions.compiled, bot_deployments.bundle_hash),
sql/18_phase5.sql (a2a_partners.bot_id).

Measured on collections (2026-09-06, alembic 20260905_0106):
  published_versions=5 (all serialize human_gates require=identity, memory),
  deployments=9, a2a_partners=1 (has fingerprint+DN, no bot_id column),
  published a2a.expose=true=0, identity_verifications verified=46,
  non-exact skill pins=0.
  No compiled backfill — compiling 5 live cards inside Alembic would
  invent artefacts the publisher did not ship. They stay NULL until republish.
  No a2a_partners.bot_id backfill — guessing a bot would reopen AUTHZ-6.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260906_0111"
down_revision: Union[str, None] = "20260906_0110"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS compiled jsonb")
    op.execute("ALTER TABLE bot_deployments ADD COLUMN IF NOT EXISTS bundle_hash TEXT")
    op.execute(
        """
        ALTER TABLE a2a_partners
          ADD COLUMN IF NOT EXISTS bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE a2a_partners
          DROP CONSTRAINT IF EXISTS a2a_partners_tenant_id_cert_fingerprint_key
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_a2a_partner_bot_cert
          ON a2a_partners (tenant_id, bot_id, cert_fingerprint)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_a2a_partner_bot_cert")
    op.execute(
        """
        ALTER TABLE a2a_partners
          ADD CONSTRAINT a2a_partners_tenant_id_cert_fingerprint_key
          UNIQUE (tenant_id, cert_fingerprint)
        """
    )
    op.execute("ALTER TABLE a2a_partners DROP COLUMN IF EXISTS bot_id")
    op.execute("ALTER TABLE bot_deployments DROP COLUMN IF EXISTS bundle_hash")
    op.execute("ALTER TABLE prompt_versions DROP COLUMN IF EXISTS compiled")
