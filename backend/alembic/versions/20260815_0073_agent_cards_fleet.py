"""One published prompt per bot; Agent Card column; eval + summary tables.

Revision ID: 20260815_0073
Revises: 20260815_0072
Create Date: 2026-08-15

The tenant-global unique on prompt_versions made a fleet impossible. Existing
rows attach to Collections (``kaia-v2-4``). First-party Intake / Insurance /
Supervisor-brief bots are inserted so later seed can publish a card on each.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260815_0073"
down_revision: Union[str, Sequence[str], None] = "20260815_0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FIRST_PARTY = (
    ("kaia-v2-4", "Collections", "2.4"),
    ("intake-v1", "Intake", "1.0"),
    ("insurance-v1", "Insurance", "1.0"),
    ("supervisor-brief", "Supervisor brief", "1.0"),
)


def upgrade() -> None:
    # First-party bots must exist before prompt_versions.bot_id can reference them.
    # Tenant comes from the existing Collections row, else the oldest tenant.
    for bot_id, name, version in _FIRST_PARTY:
        op.execute(
            f"""
            INSERT INTO bots (id, tenant_id, name, version)
            SELECT '{bot_id}',
                   COALESCE(
                     (SELECT tenant_id FROM bots WHERE id = 'kaia-v2-4' LIMIT 1),
                     (SELECT id FROM tenants ORDER BY created_at NULLS LAST, id LIMIT 1)
                   ),
                   '{name}',
                   '{version}'
            WHERE COALESCE(
                    (SELECT tenant_id FROM bots WHERE id = 'kaia-v2-4' LIMIT 1),
                    (SELECT id FROM tenants ORDER BY created_at NULLS LAST, id LIMIT 1)
                  ) IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM bots WHERE id = '{bot_id}')
            """
        )

    op.execute("ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS bot_id TEXT")
    op.execute(
        """
        UPDATE prompt_versions
           SET bot_id = 'kaia-v2-4'
         WHERE bot_id IS NULL
           AND EXISTS (SELECT 1 FROM bots WHERE id = 'kaia-v2-4')
        """
    )
    # Any leftover NULL (no bots table row) cannot become NOT NULL. Drop those
    # rows only if the install has no Collections bot at all — empty prompt
    # history on a database that never seeded is the honest outcome.
    op.execute("DELETE FROM prompt_versions WHERE bot_id IS NULL")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_prompt_versions_bot'
          ) THEN
            ALTER TABLE prompt_versions
              ADD CONSTRAINT fk_prompt_versions_bot
              FOREIGN KEY (bot_id) REFERENCES bots(id);
          END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE prompt_versions ALTER COLUMN bot_id SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompt_versions_bot_id ON prompt_versions (bot_id)"
    )

    op.execute("ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS agent_card jsonb NOT NULL DEFAULT '{}'::jsonb")

    op.execute("DROP INDEX IF EXISTS ux_prompt_versions_one_published")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_versions_one_published_per_bot
          ON prompt_versions (bot_id)
          WHERE status = 'published'
        """
    )

    op.execute(
        """
        ALTER TABLE bot_deployments
          ADD COLUMN IF NOT EXISTS traffic_pct INTEGER NOT NULL DEFAULT 100
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_bot_deployments_traffic_pct'
          ) THEN
            ALTER TABLE bot_deployments
              ADD CONSTRAINT ck_bot_deployments_traffic_pct
              CHECK (traffic_pct BETWEEN 0 AND 100);
          END IF;
        END $$;
        """
    )
    op.execute(
        "ALTER TABLE bot_deployments ADD COLUMN IF NOT EXISTS shadow boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE bot_deployments ADD COLUMN IF NOT EXISTS eval_report_id TEXT")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_suites (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          kind TEXT NOT NULL CHECK (kind IN ('regression','capability','redteam','twin')),
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_suites_tenant_id ON eval_suites(tenant_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_suites_kind ON eval_suites(kind)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_tasks (
          id TEXT PRIMARY KEY,
          suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          grader TEXT NOT NULL,
          fixture jsonb NOT NULL DEFAULT '{}'::jsonb,
          pass_bar TEXT NOT NULL DEFAULT 'all',
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_tasks_suite_id ON eval_tasks(suite_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_redteam_cases (
          id TEXT PRIMARY KEY,
          suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          attack TEXT NOT NULL,
          fixture jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_redteam_cases_suite_id ON eval_redteam_cases(suite_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_reports (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          suite_id TEXT NOT NULL REFERENCES eval_suites(id),
          bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
          prompt_version_id TEXT REFERENCES prompt_versions(id) ON DELETE SET NULL,
          status TEXT NOT NULL CHECK (status IN ('pass','fail','error')),
          summary jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_reports_tenant_id ON eval_reports(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_reports_suite_id ON eval_reports(suite_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_trials (
          id TEXT PRIMARY KEY,
          report_id TEXT NOT NULL REFERENCES eval_reports(id) ON DELETE CASCADE,
          task_id TEXT REFERENCES eval_tasks(id) ON DELETE SET NULL,
          redteam_case_id TEXT REFERENCES eval_redteam_cases(id) ON DELETE SET NULL,
          k INTEGER NOT NULL DEFAULT 1,
          passed boolean NOT NULL,
          transcript jsonb NOT NULL DEFAULT '[]'::jsonb,
          tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
          crm_outcomes jsonb NOT NULL DEFAULT '{}'::jsonb,
          grader_verdicts jsonb NOT NULL DEFAULT '[]'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_trials_report_id ON eval_trials(report_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS context_summaries (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
          upto_turn INTEGER NOT NULL,
          summary TEXT NOT NULL,
          model_profile TEXT NOT NULL DEFAULT 'analysis',
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (interaction_id, upto_turn)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_summaries_tenant_id ON context_summaries(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_summaries_interaction_id ON context_summaries(interaction_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS context_summaries")
    op.execute("DROP TABLE IF EXISTS eval_trials")
    op.execute("DROP TABLE IF EXISTS eval_reports")
    op.execute("DROP TABLE IF EXISTS eval_redteam_cases")
    op.execute("DROP TABLE IF EXISTS eval_tasks")
    op.execute("DROP TABLE IF EXISTS eval_suites")
    op.execute("ALTER TABLE bot_deployments DROP COLUMN IF EXISTS eval_report_id")
    op.execute("ALTER TABLE bot_deployments DROP COLUMN IF EXISTS shadow")
    op.execute(
        "ALTER TABLE bot_deployments DROP CONSTRAINT IF EXISTS ck_bot_deployments_traffic_pct"
    )
    op.execute("ALTER TABLE bot_deployments DROP COLUMN IF EXISTS traffic_pct")
    op.execute("DROP INDEX IF EXISTS ux_prompt_versions_one_published_per_bot")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_versions_one_published
          ON prompt_versions (tenant_id)
          WHERE status = 'published'
        """
    )
    op.execute("ALTER TABLE prompt_versions DROP COLUMN IF EXISTS agent_card")
    op.execute("ALTER TABLE prompt_versions DROP CONSTRAINT IF EXISTS fk_prompt_versions_bot")
    op.execute("DROP INDEX IF EXISTS idx_prompt_versions_bot_id")
    op.execute("ALTER TABLE prompt_versions DROP COLUMN IF EXISTS bot_id")
