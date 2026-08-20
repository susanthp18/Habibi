-- Phase 4: work runtime, simulation twin, clerk provenance, vision source, QA channel.
-- Triggers live here (sql/13 runs before this file).

ALTER TABLE treatment_decisions
  ADD COLUMN IF NOT EXISTS enacted_by TEXT;

ALTER TABLE treatment_decisions
  DROP CONSTRAINT IF EXISTS ck_treatment_decisions_enacted_by;
ALTER TABLE treatment_decisions
  ADD CONSTRAINT ck_treatment_decisions_enacted_by
  CHECK (enacted_by IS NULL OR enacted_by IN (
    'treatment_executor','clerk_agent','human','tuner'
  ));

ALTER TABLE document_requests
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'crm';

ALTER TABLE document_requests
  DROP CONSTRAINT IF EXISTS ck_document_requests_source;
ALTER TABLE document_requests
  ADD CONSTRAINT ck_document_requests_source
  CHECK (source IN ('crm','vision','clerk','mcp'));

ALTER TABLE document_requests
  DROP CONSTRAINT IF EXISTS document_requests_requested_via_check;
ALTER TABLE document_requests
  ADD CONSTRAINT document_requests_requested_via_check
  CHECK (requested_via IS NULL OR requested_via IN (
    'bot_voice','bot_chat','agent','mcp','clerk','vision','inbox'
  ));

ALTER TABLE qa_rubrics
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'voice';

ALTER TABLE qa_rubrics
  DROP CONSTRAINT IF EXISTS ck_qa_rubrics_channel;
ALTER TABLE qa_rubrics
  ADD CONSTRAINT ck_qa_rubrics_channel
  CHECK (channel IN ('voice','whatsapp','sms','chat','clerk'));

CREATE TABLE IF NOT EXISTS work_runtime_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  workflow_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'submitted'
    CHECK (status IN (
      'submitted','working','input_required','completed','failed','cancelled'
    )),
  customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  idempotency_key TEXT NOT NULL,
  input_required_reason TEXT,
  approved_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_work_runtime_jobs_tenant_status
  ON work_runtime_jobs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_work_runtime_jobs_customer
  ON work_runtime_jobs(customer_id);

CREATE TABLE IF NOT EXISTS work_runtime_signals (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES work_runtime_jobs(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_work_runtime_signals_job ON work_runtime_signals(job_id);

CREATE TABLE IF NOT EXISTS simulation_twins (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  state JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_simulation_twins_tenant ON simulation_twins(tenant_id);

CREATE TABLE IF NOT EXISTS twin_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  twin_id TEXT NOT NULL REFERENCES simulation_twins(id) ON DELETE CASCADE,
  scenario TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('running','completed','failed')),
  outcome JSONB NOT NULL DEFAULT '{}'::jsonb,
  grader JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_twin_runs_twin ON twin_runs(twin_id);

DROP TRIGGER IF EXISTS trg_work_runtime_jobs_updated_at ON work_runtime_jobs;
CREATE TRIGGER trg_work_runtime_jobs_updated_at
  BEFORE UPDATE ON work_runtime_jobs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_simulation_twins_updated_at ON simulation_twins;
CREATE TRIGGER trg_simulation_twins_updated_at
  BEFORE UPDATE ON simulation_twins
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
