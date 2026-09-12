-- W6 · decision substrate (PostgreSQL 16 fallback).
-- PostgreSQL 18 temporal primary keys are a later cutover, not a W6 runtime
-- requirement. Every temporal table uses a partial GiST exclusion constraint.

CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bank_inbound_manifests
  DROP CONSTRAINT IF EXISTS uq_bank_inbound_manifests;
ALTER TABLE bank_inbound_manifests
  ADD CONSTRAINT uq_bank_inbound_manifests UNIQUE (
    tenant_id, source, business_date, schema_version, source_ref, payload_hash
  );

ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS shard_key SMALLINT,
  ADD COLUMN IF NOT EXISTS shard_version SMALLINT;
CREATE INDEX IF NOT EXISTS idx_accounts_tenant_shard_delinquent
  ON accounts (shard_key, id)
  WHERE status = 'active' AND dpd > 0;

ALTER TABLE treatment_decisions
  ADD COLUMN IF NOT EXISTS feature_snapshot_build_id TEXT,
  ADD COLUMN IF NOT EXISTS feature_snapshot_date DATE,
  ADD COLUMN IF NOT EXISTS features_known_ts timestamptz;

ALTER TABLE usage_events
  ADD COLUMN IF NOT EXISTS decision_id TEXT
    REFERENCES treatment_decisions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_usage_events_decision
  ON usage_events (decision_id) WHERE decision_id IS NOT NULL;

CREATE OR REPLACE FUNCTION w6_guard_fact_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'W6 facts are append-only';
  END IF;
  IF (to_jsonb(NEW) - ARRAY['valid_at','valid_from','valid_to','known_to'])
       IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['valid_at','valid_from','valid_to','known_to']) THEN
    RAISE EXCEPTION 'W6 fact values and provenance are immutable';
  END IF;
  IF lower(NEW.valid_at) IS DISTINCT FROM lower(OLD.valid_at)
     OR NOT (NEW.valid_at <@ OLD.valid_at) THEN
    RAISE EXCEPTION 'W6 valid ranges may only be closed';
  END IF;
  IF OLD.known_to IS NOT NULL
     OR (NEW.known_to IS NOT NULL AND NEW.known_to < OLD.known_from) THEN
    RAISE EXCEPTION 'W6 knowledge ranges may only be closed once';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS fct_loan_state (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  external_loan_id TEXT NOT NULL,
  valid_at tstzrange NOT NULL,
  valid_from timestamptz GENERATED ALWAYS AS (lower(valid_at)) STORED,
  valid_to timestamptz GENERATED ALWAYS AS (upper(valid_at)) STORED,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL
    REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  dpd INTEGER,
  pos_paise BIGINT,
  bucket TEXT,
  status_raw TEXT,
  collectible BOOLEAN,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_loan_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT ck_fct_loan_knowledge CHECK (
    known_to IS NULL OR known_to >= known_from
  ),
  CONSTRAINT uq_fct_loan_source UNIQUE (
    tenant_id, source_manifest_id, source_row_id
  ),
  CONSTRAINT ex_fct_loan_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_loan_tenant_pit
  ON fct_loan_state (tenant_id, account_id, valid_from DESC, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_loan_known_brin
  ON fct_loan_state USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_installment (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  installment_id TEXT NOT NULL,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  due_date DATE,
  amount_paise BIGINT,
  paid_paise BIGINT,
  status TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_installment_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_installment_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_installment_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_installment_tenant_pit
  ON fct_installment (tenant_id, account_id, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_installment_known_brin
  ON fct_installment USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_mandate (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  mandate_id TEXT NOT NULL REFERENCES mandates(id) ON DELETE RESTRICT,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  rail TEXT,
  status TEXT,
  max_amount_paise BIGINT,
  debit_day SMALLINT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_mandate_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_mandate_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_mandate_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_mandate_tenant_pit
  ON fct_mandate (tenant_id, account_id, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_mandate_known_brin
  ON fct_mandate USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_presentation (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  presentation_id TEXT NOT NULL REFERENCES mandate_presentations(id) ON DELETE RESTRICT,
  mandate_id TEXT NOT NULL REFERENCES mandates(id) ON DELETE RESTRICT,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  presented_for DATE,
  amount_paise BIGINT,
  attempt_no SMALLINT,
  status TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_presentation_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_presentation_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_presentation_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_presentation_tenant_pit
  ON fct_presentation (tenant_id, account_id, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_presentation_known_brin
  ON fct_presentation USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_return (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  return_id TEXT NOT NULL,
  presentation_id TEXT NOT NULL REFERENCES mandate_presentations(id) ON DELETE RESTRICT,
  mandate_id TEXT NOT NULL REFERENCES mandates(id) ON DELETE RESTRICT,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  returned_at timestamptz,
  amount_paise BIGINT,
  return_code_raw TEXT,
  return_reason TEXT,
  retryable BOOLEAN,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_return_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_return_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_return_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_return_tenant_pit
  ON fct_return (tenant_id, account_id, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_return_known_brin
  ON fct_return USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_payment (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  payment_id TEXT NOT NULL,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  posted_at timestamptz NOT NULL,
  amount_paise BIGINT NOT NULL,
  channel TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_payment_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_payment_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_payment_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_payment_tenant_pit
  ON fct_payment (tenant_id, account_id, posted_at DESC, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_payment_known_brin
  ON fct_payment USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_contact (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  contact_id TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  account_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  occurred_at timestamptz NOT NULL,
  outcome TEXT,
  agency_id TEXT,
  agent_id TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_contact_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_contact_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_contact_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_contact_tenant_pit
  ON fct_contact (tenant_id, customer_id, occurred_at DESC, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_contact_known_brin
  ON fct_contact USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_consent (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  consent_id TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  purpose TEXT NOT NULL,
  channel TEXT NOT NULL,
  permitted BOOLEAN NOT NULL,
  event_time timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_consent_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_consent_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_consent_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_consent_tenant_pit
  ON fct_consent (tenant_id, customer_id, endpoint, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_consent_known_brin
  ON fct_consent USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_protection (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  protection_id TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  account_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT NOT NULL REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  active BOOLEAN NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  event_time timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_protection_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_protection_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_protection_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_protection_tenant_pit
  ON fct_protection (tenant_id, customer_id, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_protection_known_brin
  ON fct_protection USING brin (known_from);

CREATE TABLE IF NOT EXISTS fct_perception (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  fact_key TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  account_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT,
  valid_at tstzrange NOT NULL,
  known_from timestamptz NOT NULL,
  known_to timestamptz,
  source_manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  source_row_id TEXT NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fct_perception_valid_nonempty CHECK (NOT isempty(valid_at)),
  CONSTRAINT uq_fct_perception_source UNIQUE (tenant_id, source_manifest_id, source_row_id),
  CONSTRAINT ex_fct_perception_current EXCLUDE USING gist (
    tenant_id WITH =, fact_key WITH =, valid_at WITH &&
  ) WHERE (known_to IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fct_perception_tenant_pit
  ON fct_perception (tenant_id, customer_id, known_from DESC);
CREATE INDEX IF NOT EXISTS idx_fct_perception_known_brin
  ON fct_perception USING brin (known_from);

DROP TRIGGER IF EXISTS trg_fct_loan_state_guard ON fct_loan_state;
CREATE TRIGGER trg_fct_loan_state_guard
  BEFORE UPDATE OR DELETE ON fct_loan_state
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_installment_guard ON fct_installment;
CREATE TRIGGER trg_fct_installment_guard
  BEFORE UPDATE OR DELETE ON fct_installment
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_mandate_guard ON fct_mandate;
CREATE TRIGGER trg_fct_mandate_guard
  BEFORE UPDATE OR DELETE ON fct_mandate
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_presentation_guard ON fct_presentation;
CREATE TRIGGER trg_fct_presentation_guard
  BEFORE UPDATE OR DELETE ON fct_presentation
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_return_guard ON fct_return;
CREATE TRIGGER trg_fct_return_guard
  BEFORE UPDATE OR DELETE ON fct_return
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_payment_guard ON fct_payment;
CREATE TRIGGER trg_fct_payment_guard
  BEFORE UPDATE OR DELETE ON fct_payment
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_contact_guard ON fct_contact;
CREATE TRIGGER trg_fct_contact_guard
  BEFORE UPDATE OR DELETE ON fct_contact
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_consent_guard ON fct_consent;
CREATE TRIGGER trg_fct_consent_guard
  BEFORE UPDATE OR DELETE ON fct_consent
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_protection_guard ON fct_protection;
CREATE TRIGGER trg_fct_protection_guard
  BEFORE UPDATE OR DELETE ON fct_protection
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();
DROP TRIGGER IF EXISTS trg_fct_perception_guard ON fct_perception;
CREATE TRIGGER trg_fct_perception_guard
  BEFORE UPDATE OR DELETE ON fct_perception
  FOR EACH ROW EXECUTE FUNCTION w6_guard_fact_mutation();

CREATE TABLE IF NOT EXISTS feature_snapshot_builds (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  as_of_date DATE NOT NULL,
  feature_schema_version TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('reporting','scratch')),
  source_lsn pg_lsn,
  primary_flush_lsn pg_lsn,
  replica_lag_bytes BIGINT,
  row_count BIGINT NOT NULL DEFAULT 0,
  parquet_bytes BIGINT NOT NULL DEFAULT 0,
  stale_inputs TEXT[] NOT NULL DEFAULT '{}',
  state TEXT NOT NULL CHECK (state IN ('started','loaded','failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error TEXT,
  CONSTRAINT uq_feature_snapshot_build UNIQUE (
    tenant_id, portfolio_id, as_of_date, feature_schema_version
  )
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshot_builds_tenant
  ON feature_snapshot_builds (tenant_id, as_of_date DESC);

CREATE TABLE IF NOT EXISTS feature_snapshot_daily (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  as_of_date DATE NOT NULL,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  feature_schema_version TEXT NOT NULL,
  vector jsonb NOT NULL,
  snapshot_as_of timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  build_id TEXT NOT NULL REFERENCES feature_snapshot_builds(id) ON DELETE RESTRICT,
  built_from_lsn pg_lsn,
  primary_flush_lsn pg_lsn,
  replica_lag_bytes BIGINT,
  stale_inputs TEXT[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (
    tenant_id, portfolio_id, as_of_date, account_id, feature_schema_version
  )
) PARTITION BY RANGE (as_of_date);
CREATE TABLE IF NOT EXISTS feature_snapshot_daily_default
  PARTITION OF feature_snapshot_daily DEFAULT;
CREATE INDEX IF NOT EXISTS idx_feature_snapshot_daily_tenant_customer
  ON feature_snapshot_daily (tenant_id, customer_id, as_of_date DESC);

CREATE TABLE IF NOT EXISTS treatment_sweep_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  local_date DATE NOT NULL,
  shard_key SMALLINT NOT NULL,
  shard_version SMALLINT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','working','complete','failed')),
  eligible_count BIGINT NOT NULL DEFAULT 0,
  decided_count BIGINT NOT NULL DEFAULT 0,
  skipped_count BIGINT NOT NULL DEFAULT 0,
  retry_passes SMALLINT NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_until timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_treatment_sweep_run UNIQUE (
    tenant_id, portfolio_id, local_date, shard_version, shard_key
  )
);
CREATE INDEX IF NOT EXISTS idx_treatment_sweep_runs_claim
  ON treatment_sweep_runs (tenant_id, local_date, state, lease_until);

CREATE TABLE IF NOT EXISTS treatment_sweep_claims (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  run_id TEXT NOT NULL REFERENCES treatment_sweep_runs(id) ON DELETE RESTRICT,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  trigger_kind TEXT NOT NULL,
  local_date DATE NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('claimed','decided','skipped','failed')),
  decision_id TEXT REFERENCES treatment_decisions(id) ON DELETE SET NULL,
  lease_owner TEXT,
  lease_until timestamptz,
  error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_treatment_sweep_account_day UNIQUE (
    tenant_id, account_id, trigger_kind, local_date
  )
);
CREATE INDEX IF NOT EXISTS idx_treatment_sweep_claims_run
  ON treatment_sweep_claims (tenant_id, run_id, state, lease_until);

CREATE TABLE IF NOT EXISTS feature_pit_skew_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  sampled_from timestamptz NOT NULL,
  sampled_to timestamptz NOT NULL,
  sample_count BIGINT NOT NULL DEFAULT 0,
  mismatch_count BIGINT NOT NULL DEFAULT 0,
  state TEXT NOT NULL CHECK (state IN ('started','green','red','failed')),
  source_kind TEXT NOT NULL CHECK (source_kind IN ('reporting','scratch')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_feature_pit_skew_runs_tenant
  ON feature_pit_skew_runs (tenant_id, started_at DESC);

CREATE TABLE IF NOT EXISTS feature_pit_skew_mismatches (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  run_id TEXT NOT NULL REFERENCES feature_pit_skew_runs(id) ON DELETE RESTRICT,
  decision_id TEXT NOT NULL REFERENCES treatment_decisions(id) ON DELETE RESTRICT,
  expected_vector jsonb NOT NULL,
  observed_vector jsonb NOT NULL,
  differing_keys TEXT[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_feature_pit_skew_decision UNIQUE (run_id, decision_id)
);
CREATE INDEX IF NOT EXISTS idx_feature_pit_skew_mismatch_tenant
  ON feature_pit_skew_mismatches (tenant_id, run_id);

CREATE TABLE IF NOT EXISTS decision_cost_rollup_daily (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  usage_date DATE NOT NULL,
  decision_id TEXT NOT NULL REFERENCES treatment_decisions(id) ON DELETE RESTRICT,
  units numeric(18,6) NOT NULL,
  cost_inr numeric(14,6) NOT NULL,
  event_count BIGINT NOT NULL,
  built_from_lsn pg_lsn,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, usage_date, decision_id)
);
CREATE INDEX IF NOT EXISTS idx_decision_cost_rollup_tenant
  ON decision_cost_rollup_daily (tenant_id, usage_date DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'fk_treatment_decisions_snapshot_build'
  ) THEN
    ALTER TABLE treatment_decisions
      ADD CONSTRAINT fk_treatment_decisions_snapshot_build
      FOREIGN KEY (feature_snapshot_build_id)
      REFERENCES feature_snapshot_builds(id) ON DELETE SET NULL;
  END IF;
END $$;
