"""Skills tables (Phase 2).

Revision ID: 20260815_0075
Revises: 20260815_0074
Create Date: 2026-08-15

Signed first-party packs attach to prompt versions. Gardener drafts stay
unsigned. Mirrors sql/15_skills.sql.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260815_0075"
down_revision: Union[str, Sequence[str], None] = "20260815_0074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          slug TEXT NOT NULL,
          latest_version_id TEXT,
          signature_status TEXT NOT NULL DEFAULT 'unsigned'
            CHECK (signature_status IN ('unsigned','signed','retired')),
          origin TEXT NOT NULL DEFAULT 'first_party'
            CHECK (origin IN ('first_party','tenant','gardener')),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, slug)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_tenant_id ON skills(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills(origin)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_versions (
          id TEXT PRIMARY KEY,
          skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
          version TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft','signed','retired')),
          frontmatter jsonb NOT NULL DEFAULT '{}'::jsonb,
          body TEXT NOT NULL DEFAULT '',
          allowed_tools TEXT[] NOT NULL DEFAULT '{}',
          content_hash TEXT NOT NULL DEFAULT '',
          signature TEXT,
          signed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
          pack jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (skill_id, version)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_skill_id ON skill_versions(skill_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_status ON skill_versions(status)")

    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_skills_latest_version'
          ) THEN
            ALTER TABLE skills
              ADD CONSTRAINT fk_skills_latest_version
              FOREIGN KEY (latest_version_id) REFERENCES skill_versions(id)
              ON DELETE SET NULL;
          END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_attachments (
          prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
          skill_version_id TEXT NOT NULL REFERENCES skill_versions(id) ON DELETE CASCADE,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (prompt_version_id, skill_version_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_attachments_skill_version ON skill_attachments(skill_version_id)"
    )

    op.execute("DROP TRIGGER IF EXISTS trg_skills_updated_at ON skills")
    op.execute(
        """
        CREATE TRIGGER trg_skills_updated_at
          BEFORE UPDATE ON skills
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_skill_versions_updated_at ON skill_versions")
    op.execute(
        """
        CREATE TRIGGER trg_skill_versions_updated_at
          BEFORE UPDATE ON skill_versions
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_attachments")
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS fk_skills_latest_version")
    op.execute("DROP TABLE IF EXISTS skill_versions")
    op.execute("DROP TABLE IF EXISTS skills")
