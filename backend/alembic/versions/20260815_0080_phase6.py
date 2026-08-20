"""Phase 6 continuous evals, twin corpus, gateway model canary.

Revision ID: 20260815_0080
Revises: 20260815_0079
Create Date: 2026-08-15

Mirrors sql/19_phase6.sql. SQL is inlined so alembic does not depend on a
sibling Path read at upgrade time.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260815_0080"
down_revision: Union[str, Sequence[str], None] = "20260815_0079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE eval_reports
          ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'manual'
        """
    )
    op.execute("ALTER TABLE eval_reports DROP CONSTRAINT IF EXISTS ck_eval_reports_origin")
    op.execute(
        """
        ALTER TABLE eval_reports
          ADD CONSTRAINT ck_eval_reports_origin
          CHECK (origin IN ('manual','scheduled','canary','upgrade'))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_eval_reports_tenant_created
          ON eval_reports (tenant_id, created_at DESC)
        """
    )
    op.execute("ALTER TABLE eval_tasks ADD COLUMN IF NOT EXISTS graduated_at timestamptz")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gateway_canaries (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          candidate_model TEXT NOT NULL,
          stage TEXT NOT NULL CHECK (stage IN ('analysis','text','voice')),
          status TEXT NOT NULL CHECK (status IN ('running','pass','fail','promoted','blocked')),
          regression_report_id TEXT REFERENCES eval_reports(id) ON DELETE SET NULL,
          redteam_report_id TEXT REFERENCES eval_reports(id) ON DELETE SET NULL,
          twin_report_id TEXT REFERENCES eval_reports(id) ON DELETE SET NULL,
          voice_slo_ms INTEGER,
          injection_closed boolean NOT NULL DEFAULT false,
          copy_to_env jsonb NOT NULL DEFAULT '[]'::jsonb,
          skip_redteam boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_gateway_canaries_no_skip_redteam CHECK (skip_redteam = false)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_gateway_canaries_open
          ON gateway_canaries (tenant_id)
          WHERE status IN ('running','pass')
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gateway_canaries_tenant ON gateway_canaries (tenant_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS twin_corpus (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          source TEXT NOT NULL CHECK (source IN ('ptp_kept','bounce_chase','hardship')),
          source_ref TEXT NOT NULL,
          outcome jsonb NOT NULL DEFAULT '{}'::jsonb,
          task_id TEXT REFERENCES eval_tasks(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_twin_corpus_no_audio CHECK (
            NOT (outcome ? 'audio') AND NOT (outcome ? 'recordingUrl') AND NOT (outcome ? 'raw_audio')
          ),
          UNIQUE (tenant_id, source, source_ref)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_twin_corpus_tenant ON twin_corpus (tenant_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_critiques (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          skill_slug TEXT NOT NULL,
          report_id TEXT REFERENCES eval_reports(id) ON DELETE SET NULL,
          suggested_diff jsonb NOT NULL DEFAULT '{}'::jsonb,
          status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','merged','rejected')),
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_critiques_tenant ON skill_critiques (tenant_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_critiques")
    op.execute("DROP TABLE IF EXISTS twin_corpus")
    op.execute("DROP TABLE IF EXISTS gateway_canaries")
    op.execute("ALTER TABLE eval_tasks DROP COLUMN IF EXISTS graduated_at")
    op.execute("ALTER TABLE eval_reports DROP CONSTRAINT IF EXISTS ck_eval_reports_origin")
    op.execute("DROP INDEX IF EXISTS idx_eval_reports_tenant_created")
    op.execute("ALTER TABLE eval_reports DROP COLUMN IF EXISTS origin")
