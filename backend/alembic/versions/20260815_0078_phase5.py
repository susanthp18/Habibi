"""Phase 5 canary experiments and A2A partners/tasks.

Revision ID: 20260815_0078
Revises: 20260815_0077
Create Date: 2026-08-15

Mirrors sql/18_phase5.sql. SQL is inlined so alembic does not depend on a
sibling Path read at upgrade time.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260815_0078"
down_revision: Union[str, Sequence[str], None] = "20260815_0077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deployment_experiments (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
          environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
          canary_deployment_id TEXT NOT NULL REFERENCES bot_deployments(id) ON DELETE CASCADE,
          baseline_deployment_id TEXT REFERENCES bot_deployments(id) ON DELETE SET NULL,
          traffic_pct INTEGER NOT NULL CHECK (traffic_pct BETWEEN 0 AND 100),
          shadow boolean NOT NULL DEFAULT false,
          auto_rollback jsonb NOT NULL DEFAULT '[]'::jsonb,
          status TEXT NOT NULL CHECK (status IN ('running','rolled_back','promoted')),
          rollback_reason TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_deployment_experiments_running
          ON deployment_experiments (tenant_id, bot_id, environment)
          WHERE status = 'running'
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deployment_experiments_bot ON deployment_experiments (bot_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS a2a_partners (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          card_url TEXT NOT NULL,
          cert_fingerprint TEXT NOT NULL,
          cert_dn TEXT,
          allowed_skills TEXT[] NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','disabled')),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, cert_fingerprint)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_a2a_partners_tenant ON a2a_partners(tenant_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS a2a_tasks (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          partner_id TEXT REFERENCES a2a_partners(id) ON DELETE SET NULL,
          bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
          skill_id TEXT,
          status TEXT NOT NULL DEFAULT 'submitted'
            CHECK (status IN (
              'submitted','working','input-required','completed','failed','cancelled'
            )),
          input jsonb NOT NULL DEFAULT '{}'::jsonb,
          output jsonb NOT NULL DEFAULT '{}'::jsonb,
          cert_dn TEXT,
          error TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_a2a_tasks_tenant_status ON a2a_tasks(tenant_id, status)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_a2a_tasks_partner ON a2a_tasks(partner_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS a2a_tasks")
    op.execute("DROP TABLE IF EXISTS a2a_partners")
    op.execute("DROP TABLE IF EXISTS deployment_experiments")
