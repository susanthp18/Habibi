"""treatment_model_registry — the champion/challenger ledger.

Revision ID: 20260821_0089
Revises: 20260821_0088
Create Date: 2026-08-21

Mirrors sql/05_collections.sql.

The design note's learning loop ends with a gate: a challenger is promoted on
holdout lift, never on offline metrics alone. Everything up to that gate existed
— the corpus, the estimators, the off-policy estimators that score a candidate
policy — and the gate itself was a person deciding to copy a file.

This is the gate given a memory. A champion row cannot exist without the
evaluation that justified it, so "why is this model deciding whether to call
people?" is answerable from the database rather than from whoever remembers.

**The registry records and gates; it does not serve.** ``models.load_*`` stays a
pure file read, because it runs inside a service on the audio path of a live
call and putting Postgres between a scorer and its coefficients would trade a
real availability guarantee for a bookkeeping one. Promotion is what copies a
challenger artifact into the serving path, and ``artifact_sha`` is what keeps
that honest: it detects a file swapped underneath a promotion, which is the one
failure a registry that only stored version strings could not see.

**One champion per target, enforced by a partial unique index.** Two champions
is not a state the serving path can express — there is one file per target — so
it must not be a state the ledger can hold. Demotion is therefore not something
the promotion code has to remember to do; it is something the database will not
let it forget.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0089"
down_revision: Union[str, Sequence[str], None] = "20260821_0088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS treatment_model_registry (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          target TEXT NOT NULL CHECK (target IN ('reach','timing','uplift')),
          version TEXT NOT NULL,
          artifact_sha TEXT NOT NULL,
          artifact_path TEXT,
          status TEXT NOT NULL DEFAULT 'challenger'
            CHECK (status IN ('challenger','champion','retired','rejected')),
          corpus TEXT NOT NULL DEFAULT 'live',
          n_samples INTEGER NOT NULL DEFAULT 0,
          control_n INTEGER NOT NULL DEFAULT 0,
          segments_promoted INTEGER NOT NULL DEFAULT 0,
          metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
          evaluation jsonb,
          registered_at timestamptz NOT NULL DEFAULT now(),
          promoted_at timestamptz,
          promoted_by TEXT,
          retired_at timestamptz,
          reason TEXT,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_treatment_model_champion
          ON treatment_model_registry (tenant_id, target)
          WHERE status = 'champion'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_treatment_model_version
          ON treatment_model_registry (tenant_id, target, version, artifact_sha)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_treatment_model_registry_tenant_id
          ON treatment_model_registry(tenant_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_treatment_model_registry_target
          ON treatment_model_registry(tenant_id, target, registered_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS treatment_model_registry")
