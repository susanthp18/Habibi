-- Call intelligence: the batch pass over every finished call (call_intel/).
-- Mirrors alembic/versions/20260927_0167_call_intelligence.py.
--
-- One job per interaction, claimed by the ml_worker with SKIP LOCKED. Each
-- stage (pii, audio, signals, qa) is idempotent and recorded in stages_done,
-- so a crash resumes where it stopped and a model upgrade re-runs one stage.
-- Every model output carries the model_version that produced it: an auditor
-- can see exactly what decided a mask, a sentiment or a QA score.

CREATE TABLE IF NOT EXISTS call_intelligence_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  interaction_id TEXT NOT NULL UNIQUE REFERENCES interactions(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'done', 'failed')),
  stages_done TEXT[] NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
  available_at timestamptz NOT NULL DEFAULT now(),
  locked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_intelligence_jobs_tenant_id ON call_intelligence_jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_call_intelligence_jobs_due
  ON call_intelligence_jobs(available_at) WHERE status IN ('queued', 'running');

-- Findings from the three detectors: validated patterns, the customer's own
-- CRM values, and the PII model. needs_review marks a low-confidence mask a
-- reviewer should confirm; every finding is masked (accepted) until they do.
ALTER TABLE pii_findings DROP CONSTRAINT IF EXISTS pii_findings_type_check;
ALTER TABLE pii_findings ADD CONSTRAINT pii_findings_type_check CHECK (type IN (
  'card', 'pan', 'phone', 'email', 'address', 'dob', 'account', 'ifsc', 'aadhaar',
  'pincode', 'name', 'upi', 'passport', 'voter_id', 'driving_licence', 'secret', 'custom'));
ALTER TABLE pii_findings ADD COLUMN IF NOT EXISTS detector TEXT;
ALTER TABLE pii_findings ADD COLUMN IF NOT EXISTS model_version TEXT;
ALTER TABLE pii_findings ADD COLUMN IF NOT EXISTS needs_review boolean NOT NULL DEFAULT false;

-- Beeps at millisecond precision on one speaker's channel. source says how the
-- span was timed: word-aligned, or the whole utterance when alignment failed
-- (fail closed). at_sec/duration_sec stay for the older readers.
ALTER TABLE redaction_audio_segments ADD COLUMN IF NOT EXISTS start_ms INTEGER;
ALTER TABLE redaction_audio_segments ADD COLUMN IF NOT EXISTS end_ms INTEGER;
ALTER TABLE redaction_audio_segments ADD COLUMN IF NOT EXISTS channel TEXT
  CHECK (channel IN ('customer', 'agent'));
ALTER TABLE redaction_audio_segments ADD COLUMN IF NOT EXISTS source TEXT
  CHECK (source IN ('aligned', 'utterance_fallback', 'manual'));

-- A tenant's own pattern (custom rules) and the label the PII model looks for.
ALTER TABLE redaction_rule_configs ADD COLUMN IF NOT EXISTS pattern TEXT;
ALTER TABLE redaction_rule_configs ADD COLUMN IF NOT EXISTS model_label TEXT;

-- Per-turn conversation signals: customer sentiment, customer intents, agent
-- behaviour, disclosures. QA, Audit and Bot analytics read these.
CREATE TABLE IF NOT EXISTS interaction_turn_signals (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  transcript_turn_id TEXT NOT NULL REFERENCES interaction_transcript(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('sentiment', 'intent', 'behaviour', 'disclosure')),
  label TEXT NOT NULL,
  score numeric(5,3) NOT NULL,
  model_version TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (transcript_turn_id, kind, label)
);
CREATE INDEX IF NOT EXISTS idx_interaction_turn_signals_interaction_id
  ON interaction_turn_signals(interaction_id);

-- How each QA criterion was decided: tier 0 evidence, tier 1 small model,
-- tier 2 LLM judge, or a human. Evidence names the transcript turns.
ALTER TABLE qa_scorecard_entries ADD COLUMN IF NOT EXISTS tier TEXT
  CHECK (tier IN ('evidence', 'model', 'llm', 'human'));
ALTER TABLE qa_scorecard_entries ADD COLUMN IF NOT EXISTS confidence numeric(5,3);
ALTER TABLE qa_scorecard_entries ADD COLUMN IF NOT EXISTS evidence JSONB;
ALTER TABLE qa_scorecard_entries ADD COLUMN IF NOT EXISTS model_version TEXT;

-- Exports are built by the ml_worker (call_intel/exports.py), not inside the
-- request: a bundle of recordings can take minutes. 'running' is a claimed job.
ALTER TABLE export_jobs DROP CONSTRAINT IF EXISTS export_jobs_status_check;
ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_status_check
  CHECK (status IN ('queued', 'running', 'ready', 'failed'));
ALTER TABLE export_jobs ADD COLUMN IF NOT EXISTS locked_at timestamptz;
ALTER TABLE export_jobs ADD COLUMN IF NOT EXISTS error TEXT;
