-- W5 · the bank boundary.
-- Generic production contracts and deterministic reference-adapter ledgers.
-- Real-bank adapters stay unavailable until signed dictionaries arrive.
-- Amounts are integer paise. known_from is arrival time and is never back-dated.
-- Evidence FKs are RESTRICT. Tenant-leading indexes.

CREATE OR REPLACE FUNCTION w5_reject_immutable_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'W5 evidence is immutable';
END;
$$;

CREATE TABLE IF NOT EXISTS bank_contracts (
  code TEXT PRIMARY KEY,
  family TEXT NOT NULL CHECK (family IN ('inbound','outbound','fairness')),
  grain TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO bank_contracts (code, family, grain, description) VALUES
  ('C1', 'inbound', 'account', 'book.account'),
  ('C2', 'inbound', 'installment', 'installment schedule'),
  ('C3', 'inbound', 'mandate', 'mandate authority'),
  ('C4', 'inbound', 'presentation', 'mandate presentation'),
  ('C5', 'inbound', 'presentation_return', 'mandate return / settlement'),
  ('C6', 'inbound', 'payment', 'payment / ledger posting'),
  ('C7', 'inbound', 'external_contact', 'bank/agency CDR / contact ledger'),
  ('C8', 'inbound', 'endpoint_purpose', 'consent at endpoint × purpose'),
  ('C9', 'inbound', 'capacity_roster', 'resource capacity and agency roster'),
  ('C10', 'inbound', 'protection', 'servicing protection facts'),
  ('F8', 'inbound', 'complaint', 'conduct complaint / grievance'),
  ('F9', 'fairness', 'protected_attribute', 'protected attributes (evaluation schema)'),
  ('O1', 'outbound', 'message', 'send.message'),
  ('O2', 'outbound', 'rail', 'rail / LMS presentment submit'),
  ('O3', 'outbound', 'cdr_writeback', 'CDR writeback'),
  ('O4', 'outbound', 'consent_writeback', 'consent writeback'),
  ('O5', 'outbound', 'complaint_filing', 'complaint filing'),
  ('O6', 'outbound', 'lms_workitem', 'LMS work item')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS bank_contract_versions (
  contract_code TEXT NOT NULL REFERENCES bank_contracts(code) ON DELETE RESTRICT,
  schema_version TEXT NOT NULL,
  schema_digest TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (contract_code, schema_version)
);

INSERT INTO bank_contract_versions (contract_code, schema_version, schema_digest)
SELECT code, 'bank-boundary.v1', 'sha256:reference-v1'
  FROM bank_contracts
ON CONFLICT (contract_code, schema_version) DO NOTHING;

INSERT INTO permissions (id, module, action, description) VALUES
  (
    'perm-bank-boundary-read', 'bank_boundary', 'read',
    'Read bank-boundary contracts, manifests, readiness and outbox'
  ),
  (
    'perm-bank-boundary-write', 'bank_boundary', 'write',
    'Ingest bank-boundary manifests and file complaints'
  )
ON CONFLICT (id) DO UPDATE SET
  module = EXCLUDED.module,
  action = EXCLUDED.action,
  description = EXCLUDED.description;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.permission_id
  FROM roles r
  CROSS JOIN (
    VALUES
      ('role-supervisor', 'perm-bank-boundary-read'),
      ('role-admin', 'perm-bank-boundary-read'),
      ('role-admin', 'perm-bank-boundary-write')
  ) AS p(role_id, permission_id)
 WHERE r.id = p.role_id
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS bank_contract_bindings (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  contract_code TEXT NOT NULL REFERENCES bank_contracts(code),
  schema_version TEXT NOT NULL,
  adapter TEXT NOT NULL DEFAULT 'reference',
  state TEXT NOT NULL DEFAULT 'shadow' CHECK (state IN ('shadow','ready','live','blocked')),
  bound_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_bank_contract_binding_version
    FOREIGN KEY (contract_code, schema_version)
    REFERENCES bank_contract_versions(contract_code, schema_version)
    ON DELETE RESTRICT,
  CONSTRAINT uq_bank_contract_bindings UNIQUE (tenant_id, portfolio_id, contract_code)
);
CREATE INDEX IF NOT EXISTS idx_bank_contract_bindings_tenant
  ON bank_contract_bindings (tenant_id, contract_code);

CREATE TABLE IF NOT EXISTS bank_inbound_manifests (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  contract_code TEXT NOT NULL REFERENCES bank_contracts(code),
  schema_version TEXT NOT NULL,
  source TEXT NOT NULL,
  business_date date NOT NULL,
  source_ref TEXT NOT NULL,
  control_count INTEGER NOT NULL,
  control_sum_paise BIGINT NOT NULL,
  payload_hash TEXT NOT NULL,
  event_time timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('accepted','rejected')),
  reject_reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bank_manifests_known_from CHECK (known_from >= event_time),
  CONSTRAINT fk_bank_manifest_version
    FOREIGN KEY (contract_code, schema_version)
    REFERENCES bank_contract_versions(contract_code, schema_version)
    ON DELETE RESTRICT,
  CONSTRAINT uq_bank_inbound_manifests UNIQUE (
    tenant_id, source, business_date, schema_version, source_ref, payload_hash
  )
);
CREATE INDEX IF NOT EXISTS idx_bank_inbound_manifests_tenant
  ON bank_inbound_manifests (tenant_id, contract_code, business_date DESC);
DROP TRIGGER IF EXISTS trg_bank_inbound_manifests_immutable
  ON bank_inbound_manifests;
CREATE TRIGGER trg_bank_inbound_manifests_immutable
BEFORE UPDATE OR DELETE ON bank_inbound_manifests
FOR EACH ROW EXECUTE FUNCTION w5_reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS bank_reconciliation_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  contract_code TEXT NOT NULL REFERENCES bank_contracts(code),
  business_date date NOT NULL,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  status TEXT NOT NULL CHECK (status IN ('matched','break','stale')),
  observed_count INTEGER NOT NULL DEFAULT 0,
  observed_sum_paise BIGINT NOT NULL DEFAULT 0,
  control_count INTEGER NOT NULL DEFAULT 0,
  control_sum_paise BIGINT NOT NULL DEFAULT 0,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bank_reconciliation_runs_tenant
  ON bank_reconciliation_runs (tenant_id, contract_code, business_date DESC);

CREATE TABLE IF NOT EXISTS bank_reconciliation_breaks (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES bank_reconciliation_runs(id) ON DELETE RESTRICT,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  kind TEXT NOT NULL CHECK (kind IN (
    'count','sum','duplicate','temporal','ownership','binding',
    'contract_version','validation','unknown_map','backdated','hash_mismatch'
  )),
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bank_reconciliation_breaks_tenant
  ON bank_reconciliation_breaks (tenant_id, kind, created_at DESC);

CREATE TABLE IF NOT EXISTS bank_freshness (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  portfolio_id TEXT NOT NULL DEFAULT '',
  contract_code TEXT NOT NULL REFERENCES bank_contracts(code),
  last_accepted_at timestamptz,
  last_business_date date,
  consecutive_ok_days INTEGER NOT NULL DEFAULT 0,
  lag_hours numeric(10,2),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, portfolio_id, contract_code)
);

CREATE TABLE IF NOT EXISTS bank_id_map (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  namespace TEXT NOT NULL,
  external_id TEXT NOT NULL,
  canonical_id TEXT NOT NULL,
  canonical_table TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, namespace, external_id)
);
CREATE INDEX IF NOT EXISTS idx_bank_id_map_canonical
  ON bank_id_map (tenant_id, canonical_table, canonical_id);

CREATE TABLE IF NOT EXISTS action_contracts (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  decision_id TEXT NOT NULL REFERENCES treatment_decisions(id) ON DELETE RESTRICT,
  version TEXT NOT NULL,
  digest TEXT NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_action_contracts_decision UNIQUE (decision_id)
);
CREATE INDEX IF NOT EXISTS idx_action_contracts_tenant
  ON action_contracts (tenant_id, created_at DESC);
DROP TRIGGER IF EXISTS trg_action_contracts_immutable ON action_contracts;
CREATE TRIGGER trg_action_contracts_immutable
BEFORE UPDATE OR DELETE ON action_contracts
FOR EACH ROW EXECUTE FUNCTION w5_reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS bank_outbound_outbox (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  contract_code TEXT NOT NULL REFERENCES bank_contracts(code),
  action_contract_id TEXT REFERENCES action_contracts(id) ON DELETE RESTRICT,
  decision_id TEXT,
  idempotency_key TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN (
    'pending','sent','acked','reconciled','awaiting_settlement','parked','rejected'
  )),
  park_reason TEXT,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_bank_outbound_outbox_key UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_bank_outbound_outbox_tenant
  ON bank_outbound_outbox (tenant_id, state, created_at);

CREATE TABLE IF NOT EXISTS bank_outbound_acks (
  id TEXT PRIMARY KEY,
  outbox_id TEXT NOT NULL REFERENCES bank_outbound_outbox(id) ON DELETE RESTRICT,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  provider_ref TEXT NOT NULL,
  status TEXT NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT uq_bank_outbound_acks UNIQUE (outbox_id, provider_ref, status)
);
CREATE INDEX IF NOT EXISTS idx_bank_outbound_acks_tenant
  ON bank_outbound_acks (tenant_id, received_at DESC);

-- Fail-closed mapping catalogues (§7.6). Unknown values never fall through.
CREATE TABLE IF NOT EXISTS rail_return_codes (
  namespace TEXT NOT NULL,
  code TEXT NOT NULL,
  normalised TEXT NOT NULL CHECK (normalised IN (
    'insufficient_funds','account_closed','mandate_expired','technical','unknown'
  )),
  retryable BOOLEAN NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (namespace, code)
);

CREATE TABLE IF NOT EXISTS lms_account_status (
  namespace TEXT NOT NULL,
  code TEXT NOT NULL,
  normalised TEXT NOT NULL CHECK (normalised IN (
    'active','closed','charged_off','sold','frozen','unknown'
  )),
  contacting_permitted BOOLEAN NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (namespace, code)
);

CREATE TABLE IF NOT EXISTS dlt_templates (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  template_id TEXT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('sms','whatsapp')),
  body_hash TEXT NOT NULL,
  required_assertions jsonb NOT NULL DEFAULT '[]'::jsonb,
  state TEXT NOT NULL DEFAULT 'draft' CHECK (state IN (
    'draft','submitted','approved','rejected'
  )),
  submitted_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  approved_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_dlt_templates UNIQUE (tenant_id, template_id, channel),
  CONSTRAINT ck_dlt_templates_maker_checker CHECK (
    state <> 'approved'
    OR (
      submitted_by_user_id IS NOT NULL
      AND approved_by_user_id IS NOT NULL
      AND approved_by_user_id <> submitted_by_user_id
      AND approved_at IS NOT NULL
      AND jsonb_array_length(required_assertions) > 0
    )
  )
);
CREATE INDEX IF NOT EXISTS idx_dlt_templates_tenant
  ON dlt_templates (tenant_id, state);

CREATE TABLE IF NOT EXISTS bank_mapping_reviews (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  catalogue TEXT NOT NULL CHECK (catalogue IN (
    'rail_return_codes','lms_account_status','dlt_templates'
  )),
  raw_value TEXT NOT NULL,
  contract_code TEXT,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','mapped','dismissed')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bank_mapping_reviews_open
  ON bank_mapping_reviews (tenant_id, state, created_at);

CREATE TABLE IF NOT EXISTS bank_consent_snapshots (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  endpoint TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK (purpose IN ('servicing','promotional','all')),
  channel TEXT NOT NULL CHECK (channel IN (
    'voice','whatsapp','sms','email','chat','field','all'
  )),
  permitted BOOLEAN NOT NULL,
  source_ref TEXT,
  event_time timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bank_consent_known_from CHECK (known_from >= event_time),
  CONSTRAINT uq_bank_consent_snapshots UNIQUE (
    tenant_id, customer_id, endpoint, purpose, channel, event_time
  )
);
CREATE INDEX IF NOT EXISTS idx_bank_consent_snapshots_customer
  ON bank_consent_snapshots (tenant_id, customer_id, known_from DESC);

CREATE TABLE IF NOT EXISTS bank_external_contacts (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  customer_id TEXT REFERENCES customers_pii(id) ON DELETE RESTRICT,
  external_key TEXT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN (
    'voice','whatsapp','sms','email','chat','field'
  )),
  occurred_at timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  agency_id TEXT,
  agent_id TEXT,
  outcome TEXT,
  source_ref TEXT,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bank_external_contact_known_from CHECK (known_from >= occurred_at),
  CONSTRAINT uq_bank_external_contacts UNIQUE (tenant_id, external_key)
);
CREATE INDEX IF NOT EXISTS idx_bank_external_contacts_customer
  ON bank_external_contacts (tenant_id, customer_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS bank_capacity (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  plan_date date NOT NULL,
  resource TEXT NOT NULL,
  capacity_units numeric(14,2) NOT NULL,
  known_from timestamptz NOT NULL,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_bank_capacity UNIQUE (tenant_id, plan_date, resource)
);
CREATE INDEX IF NOT EXISTS idx_bank_capacity_tenant
  ON bank_capacity (tenant_id, plan_date);

CREATE TABLE IF NOT EXISTS bank_agency_roster (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  agency_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  certification TEXT NOT NULL,
  expires_at timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_bank_agency_roster UNIQUE (tenant_id, agency_id, agent_id, certification)
);
CREATE INDEX IF NOT EXISTS idx_bank_agency_roster_tenant
  ON bank_agency_roster (tenant_id, expires_at);

CREATE TABLE IF NOT EXISTS bank_protections (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  account_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT,
  kind TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  event_time timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bank_protection_known_from CHECK (known_from >= event_time)
);
CREATE INDEX IF NOT EXISTS idx_bank_protections_customer
  ON bank_protections (tenant_id, customer_id, known_from DESC);

CREATE TABLE IF NOT EXISTS bank_complaint_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  direction TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  kind TEXT NOT NULL,
  clock_due_at timestamptz,
  decision_id TEXT REFERENCES treatment_decisions(id) ON DELETE RESTRICT,
  contact_event_id TEXT,
  outbox_id TEXT REFERENCES bank_outbound_outbox(id) ON DELETE RESTRICT,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  event_time timestamptz NOT NULL,
  known_from timestamptz NOT NULL,
  manifest_id TEXT REFERENCES bank_inbound_manifests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bank_complaint_known_from CHECK (known_from >= event_time)
);
CREATE INDEX IF NOT EXISTS idx_bank_complaint_events_customer
  ON bank_complaint_events (tenant_id, customer_id, event_time DESC);

CREATE TABLE IF NOT EXISTS bank_breach_audits (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  breaches INTEGER NOT NULL DEFAULT 0,
  ledger_coverage_share numeric(7,4),
  sources_represented jsonb NOT NULL DEFAULT '[]'::jsonb,
  green BOOLEAN NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bank_breach_audits_tenant
  ON bank_breach_audits (tenant_id, created_at DESC);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'enactment_attempts'
       AND column_name = 'action_contract_id'
  ) AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_enactment_attempts_action_contract'
  ) THEN
    ALTER TABLE enactment_attempts
      ADD CONSTRAINT fk_enactment_attempts_action_contract
      FOREIGN KEY (action_contract_id) REFERENCES action_contracts(id) ON DELETE RESTRICT;
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS evaluation;

CREATE TABLE IF NOT EXISTS evaluation.protected_attributes (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  attribute_name TEXT NOT NULL,
  attribute_value_hash TEXT NOT NULL,
  source_ref TEXT,
  known_from timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_eval_protected UNIQUE (tenant_id, customer_id, attribute_name)
);

CREATE TABLE IF NOT EXISTS evaluation.fairness_readiness (
  tenant_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL DEFAULT '',
  covered BOOLEAN NOT NULL DEFAULT false,
  n_subjects INTEGER NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, portfolio_id)
);

REVOKE ALL ON SCHEMA evaluation FROM PUBLIC;
GRANT USAGE ON SCHEMA evaluation TO CURRENT_USER;
GRANT SELECT ON evaluation.fairness_readiness TO CURRENT_USER;
REVOKE ALL ON evaluation.protected_attributes FROM PUBLIC;
-- W5_ROLE_DDL_BEGIN
DO $$
BEGIN
  CREATE ROLE evaluation_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$
BEGIN
  CREATE ROLE evaluation_role NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER SCHEMA evaluation OWNER TO evaluation_owner;
ALTER TABLE evaluation.protected_attributes OWNER TO evaluation_owner;
ALTER TABLE evaluation.fairness_readiness OWNER TO evaluation_owner;
REVOKE ALL ON evaluation.protected_attributes FROM CURRENT_USER;
REVOKE ALL ON evaluation.protected_attributes FROM PUBLIC;
GRANT USAGE ON SCHEMA evaluation TO evaluation_role;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON evaluation.protected_attributes TO evaluation_role;
GRANT SELECT, INSERT, UPDATE
  ON evaluation.fairness_readiness TO evaluation_role;
-- W5_ROLE_DDL_END

