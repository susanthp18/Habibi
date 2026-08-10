"""Production hardening invariants surfaced by the backend review.

* ``kb_index_jobs.attempt`` + ``dead`` status so stuck-job reclaim is bounded
  instead of re-queueing a poison job forever.
* ``uq_budgets_tenant_env_month`` — tenant-scoped budgets were unconstrained;
  only the org-wide (``tenant_id IS NULL``) rows had a uniqueness guarantee.
* ``idempotency_keys`` identity becomes ``(endpoint, key)``. The reader already
  filtered on both columns while the PK was ``key`` alone, so the same key
  reused on a second endpoint stored nothing and replayed as a fresh write.
* Seed the ``standard`` ``tts_price_tiers`` row that ``tts_voice_catalog``
  defaults its FK to.
* ``messages.bot_turn_job_id`` gets its missing FK to ``bot_turn_jobs``.

Revision ID: 20260725_0040
Revises: 20260725_0039
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0040"
down_revision: Union[str, Sequence[str], None] = "20260725_0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- kb_index_jobs: bounded reclaim -----------------------------------
    # Keep the server default: enqueue_index_job does not list `attempt`, and
    # sql/09_bot_config.sql declares it DEFAULT 0 — dropping it here would make
    # every insert fail the NOT NULL check.
    op.add_column(
        "kb_index_jobs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE kb_index_jobs SET attempt = 1 WHERE status <> 'queued'")
    op.execute("ALTER TABLE kb_index_jobs DROP CONSTRAINT IF EXISTS kb_index_jobs_status_check")
    op.execute(
        """
        ALTER TABLE kb_index_jobs
          ADD CONSTRAINT kb_index_jobs_status_check
          CHECK (status IN ('queued','running','succeeded','failed','dead'))
        """
    )

    # --- budgets: tenant-scoped uniqueness --------------------------------
    # Collapse pre-existing duplicates onto the newest row so the index can be
    # created; billing reads the latest row anyway.
    op.execute(
        """
        DELETE FROM budgets b
        USING budgets keep
        WHERE b.tenant_id IS NOT NULL
          AND keep.tenant_id = b.tenant_id
          AND keep.environment = b.environment
          AND keep.month = b.month
          AND (keep.updated_at, keep.id) > (b.updated_at, b.id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_budgets_tenant_env_month
          ON budgets (tenant_id, environment, month) WHERE tenant_id IS NOT NULL
        """
    )

    # --- idempotency_keys: identity is (endpoint, key) --------------------
    op.execute("ALTER TABLE idempotency_keys DROP CONSTRAINT idempotency_keys_pkey")
    op.execute("ALTER TABLE idempotency_keys ADD PRIMARY KEY (endpoint, key)")

    # --- tts price tier seed ----------------------------------------------
    op.execute(
        """
        INSERT INTO tts_price_tiers (tier, label, approx_usd_per_1m_chars, is_premium, notes)
        VALUES ('standard', 'Standard neural', 15.0, false, 'Default tier for catalog voices')
        ON CONFLICT (tier) DO NOTHING
        """
    )

    # --- shared KB rate-limit counters ------------------------------------
    op.create_table(
        "kb_rate_limit_counters",
        sa.Column("bucket", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_kb_rate_limit_counters_window", "kb_rate_limit_counters", ["window_start"]
    )

    # --- provider_configs: tenant-scoped uniqueness -----------------------
    # The upsert keyed on the surrogate id `pcfg-{provider}-{env}`, which omits
    # the tenant, so a second tenant's write overwrote the first tenant's row.
    op.execute(
        """
        DELETE FROM provider_configs c
        USING provider_configs keep
        WHERE keep.provider_id = c.provider_id
          AND keep.tenant_id = c.tenant_id
          AND keep.environment = c.environment
          AND (keep.updated_at, keep.id) > (c.updated_at, c.id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_provider_configs_provider_tenant_env
          ON provider_configs (provider_id, tenant_id, environment)
        """
    )

    # --- account tail lookup indexes --------------------------------------
    # capture.find_customer_by_account_tail runs on the live-call identity path.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_accounts_digit_tail4
          ON accounts ((RIGHT(regexp_replace(id, '[^0-9]', '', 'g'), 4)))
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_accounts_id_tail4 ON accounts ((RIGHT(id, 4)))")

    # --- messages.bot_turn_job_id referential integrity --------------------
    op.execute(
        """
        UPDATE messages m
        SET bot_turn_job_id = NULL
        WHERE bot_turn_job_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM bot_turn_jobs j WHERE j.id = m.bot_turn_job_id)
        """
    )
    op.create_foreign_key(
        "fk_messages_bot_turn_job",
        "messages",
        "bot_turn_jobs",
        ["bot_turn_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_messages_bot_turn_job", "messages", type_="foreignkey")

    op.execute("DROP INDEX IF EXISTS idx_accounts_id_tail4")
    op.execute("DROP INDEX IF EXISTS idx_accounts_digit_tail4")
    op.execute("DROP INDEX IF EXISTS uq_provider_configs_provider_tenant_env")

    op.drop_index("idx_kb_rate_limit_counters_window", table_name="kb_rate_limit_counters")
    op.drop_table("kb_rate_limit_counters")

    # tts_price_tiers seed is left in place: tts_voice_catalog rows FK to it.

    op.execute("ALTER TABLE idempotency_keys DROP CONSTRAINT idempotency_keys_pkey")
    # Collapse to one row per key before restoring the narrower PK.
    op.execute(
        """
        DELETE FROM idempotency_keys a
        USING idempotency_keys b
        WHERE a.key = b.key AND (b.created_at, b.endpoint) > (a.created_at, a.endpoint)
        """
    )
    op.execute("ALTER TABLE idempotency_keys ADD PRIMARY KEY (key)")

    op.execute("DROP INDEX IF EXISTS uq_budgets_tenant_env_month")

    op.execute("ALTER TABLE kb_index_jobs DROP CONSTRAINT IF EXISTS kb_index_jobs_status_check")
    op.execute("UPDATE kb_index_jobs SET status = 'failed' WHERE status = 'dead'")
    op.execute(
        """
        ALTER TABLE kb_index_jobs
          ADD CONSTRAINT kb_index_jobs_status_check
          CHECK (status IN ('queued','running','succeeded','failed'))
        """
    )
    op.drop_column("kb_index_jobs", "attempt")
