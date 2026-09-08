"""Honest engines W0–W3: vocabulary, attempts, logging contract, parked.

Revision ID: 20260906_0107
Revises: 20260905_0106
Create Date: 2026-09-06

Does not rewrite historical outcomes. Pre-cutover fused-propensity rows remain
logging-contract v1 and are permanently excluded from OPE by that version.

NOT applied to the running database by this work package. Mirror:
sql/05_collections.sql, sql/06_sales.sql, sql/12_crosscutting.sql,
sql/22_campaigns.sql, sql/02_customer_account.sql.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260906_0107"
down_revision: Union[str, None] = "20260905_0106"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODE = "mode IN ('off','shadow','live','simulated')"
_ACTION = (
    "chosen_action IS NULL OR chosen_action IN ("
    "'wait','sms','whatsapp','voice_bot','human_call','field_visit',"
    "'legal_notice','represent_mandate','emi_date_change','self_service_plan')"
)
_OUTCOME = (
    "outcome IS NULL OR outcome IN ("
    "'reached','no_answer','paid','ptp','refused','undeliverable',"
    "'cancelled','superseded','unresolved')"
)
_CANCEL = (
    "cancel_reason IS NULL OR cancel_reason IN ("
    "'plan_expired','no_executor','unknown_action','customer_row_missing',"
    "'contact_gate_refused','handler_exception','paid_since_decision',"
    "'policy_effective_change','window_edge_capacity',"
    "'prerequisite_not_delivered','endpoint_unverified')"
)


def _drop_both(table: str, names: tuple[str, ...]) -> None:
    for name in names:
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}')


def _add_not_valid(table: str, name: str, expr: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID"
    )


def _validate(table: str, name: str) -> None:
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    # W0 — repair CHECK chains. Drop both historical spellings, re-add with
    # NOT VALID, then VALIDATE so existing rows are checked without a long
    # ACCESS EXCLUSIVE rewrite.
    _drop_both(
        "treatment_decisions",
        ("ck_treatment_decisions_mode", "treatment_decisions_mode_check"),
    )
    _add_not_valid("treatment_decisions", "ck_treatment_decisions_mode", _MODE)
    _validate("treatment_decisions", "ck_treatment_decisions_mode")

    _drop_both(
        "treatment_decisions",
        (
            "ck_treatment_decisions_action",
            "treatment_decisions_chosen_action_check",
            "treatment_decisions_action_check",
        ),
    )
    _add_not_valid("treatment_decisions", "ck_treatment_decisions_action", _ACTION)
    _validate("treatment_decisions", "ck_treatment_decisions_action")

    _drop_both(
        "treatment_decisions",
        ("ck_treatment_decisions_outcome", "treatment_decisions_outcome_check"),
    )
    _add_not_valid("treatment_decisions", "ck_treatment_decisions_outcome", _OUTCOME)
    _validate("treatment_decisions", "ck_treatment_decisions_outcome")

    # W1 — cancel_reason, leases, attempts, reservations, WhatsApp decision_id,
    # campaign parked.
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS cancel_reason TEXT"
    )
    _add_not_valid("treatment_decisions", "ck_treatment_decisions_cancel_reason", _CANCEL)
    _validate("treatment_decisions", "ck_treatment_decisions_cancel_reason")

    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS claimed_at timestamptz"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS lease_until timestamptz"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS lease_owner TEXT"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enactment_attempts (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          decision_id TEXT NOT NULL REFERENCES treatment_decisions(id) ON DELETE CASCADE,
          channel TEXT NOT NULL,
          action TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          state TEXT NOT NULL,
          provider_ref TEXT,
          error TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_enactment_attempts_state CHECK (
            state IN ('claimed','committed','queued','sent','failed','parked','reconciled')
          ),
          CONSTRAINT uq_enactment_attempts_key UNIQUE (idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_enactment_attempts_decision "
        "ON enactment_attempts (decision_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_reservations (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
          decision_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          state TEXT NOT NULL,
          provider_ref TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_contact_reservations_state CHECK (
            state IN ('held','committed','released')
          ),
          CONSTRAINT uq_contact_reservations_decision_channel UNIQUE (decision_id, channel)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contact_reservations_customer "
        "ON contact_reservations (customer_id, state)"
    )

    op.execute(
        "ALTER TABLE whatsapp_outbound_jobs ADD COLUMN IF NOT EXISTS decision_id TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_whatsapp_outbound_jobs_decision "
        "ON whatsapp_outbound_jobs (decision_id) WHERE decision_id IS NOT NULL"
    )

    op.execute(
        "ALTER TABLE campaign_targets DROP CONSTRAINT IF EXISTS ck_campaign_targets_state"
    )
    op.execute(
        "ALTER TABLE campaign_targets DROP CONSTRAINT IF EXISTS campaign_targets_state_check"
    )
    _add_not_valid(
        "campaign_targets",
        "ck_campaign_targets_state",
        "state IN ('pending','dialing','done','failed','skipped','parked')",
    )
    _validate("campaign_targets", "ck_campaign_targets_state")

    # W2 — dual propensities and provenance on both logs.
    for col, typ in (
        ("arm_propensity", "double precision"),
        ("action_propensity", "double precision"),
        ("replay_nonce", "TEXT"),
        ("veto_stack_version", "TEXT"),
        ("engine_image_digest", "TEXT"),
        ("config_version", "TEXT"),
        ("lambda_bucket", "TEXT"),
        ("logging_contract_version", "INTEGER"),
    ):
        op.execute(
            f"ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS {col} {typ}"
        )
        op.execute(
            f"ALTER TABLE offer_decisions ADD COLUMN IF NOT EXISTS {col} {typ}"
        )

    op.execute(
        "ALTER TABLE treatment_decisions ALTER COLUMN lambda_bucket SET DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE offer_decisions ALTER COLUMN lambda_bucket SET DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ALTER COLUMN logging_contract_version SET DEFAULT 2"
    )
    op.execute(
        "ALTER TABLE offer_decisions ALTER COLUMN logging_contract_version SET DEFAULT 2"
    )
    # Historical rows stay v1. Do not backfill propensities.
    op.execute(
        "UPDATE treatment_decisions SET logging_contract_version = 1 "
        "WHERE logging_contract_version IS NULL"
    )
    op.execute(
        "UPDATE offer_decisions SET logging_contract_version = 1 "
        "WHERE logging_contract_version IS NULL"
    )

    # W3 — reach vs cure, label maturity.
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS reach_outcome TEXT"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS cure_outcome TEXT"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS observed_days INTEGER"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS event_at timestamptz"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS label_mature_at timestamptz"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS label_definition_version TEXT"
    )

    # Money-path: reversal is a first-class ledger type.
    op.execute(
        "ALTER TABLE ledger_entries DROP CONSTRAINT IF EXISTS ledger_entries_type_check"
    )
    op.execute(
        "ALTER TABLE ledger_entries DROP CONSTRAINT IF EXISTS ck_ledger_entries_type"
    )
    _add_not_valid(
        "ledger_entries",
        "ck_ledger_entries_type",
        "type IN ('charge','payment','fee','adjustment','waiver','reversal')",
    )
    _validate("ledger_entries", "ck_ledger_entries_type")
    op.execute(
        "ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS reverses_id TEXT"
    )

    # Optional payload sidecar (expand). Empty until dual-write is switched on.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS treatment_decision_payloads (
          decision_id TEXT PRIMARY KEY
            REFERENCES treatment_decisions(id) ON DELETE CASCADE,
          features jsonb NOT NULL DEFAULT '{}'::jsonb,
          candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
          excluded jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # RLS claimer role — prepared, not enabled. Orchestrator activates.
    op.execute("DO $$ BEGIN CREATE ROLE claimer NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute("GRANT SELECT, UPDATE ON treatment_decisions TO claimer")
    op.execute("GRANT SELECT, INSERT, UPDATE ON enactment_attempts TO claimer")
    op.execute("GRANT SELECT, INSERT, UPDATE ON contact_reservations TO claimer")


def downgrade() -> None:
    # Forward-only. A downgrade would drop evidence columns.
    return
