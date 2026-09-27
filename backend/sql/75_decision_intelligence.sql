-- Decision intelligence v2: what the engine has learned, and the proposals a
-- person approves before configuration changes. Additive; row security comes
-- from scripts/rls.py like every tenant table.

-- Response rates learned from labelled decisions, per family / metric / key
-- (a channel for reach, an action for resolve, a product for offers). Counts,
-- not means: the scorer shrinks them toward its starting assumption at read
-- time, so changing an assumption moves the estimate without a recompute.
CREATE TABLE IF NOT EXISTS treatment_beliefs (
  tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  family       TEXT NOT NULL CHECK (family IN ('collections','offer')),
  metric       TEXT NOT NULL CHECK (metric IN ('reach','resolve','response')),
  key          TEXT NOT NULL,
  successes    INTEGER NOT NULL CHECK (successes >= 0),
  trials       INTEGER NOT NULL CHECK (trials >= successes),
  window_days  INTEGER NOT NULL,
  computed_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, family, metric, key)
);

-- A change to the engine's configuration, proposed by a person or by the
-- weekly advisor, applied only when somebody other than its author approves.
-- Approval writes engine_config through its own maker-checker path.
CREATE TABLE IF NOT EXISTS engine_config_proposals (
  id            TEXT PRIMARY KEY,
  tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  changes       JSONB NOT NULL,
  reason        TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
  evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
  impact        JSONB NOT NULL DEFAULT '{}'::jsonb,
  proposed_by   TEXT NOT NULL,
  proposed_via  TEXT NOT NULL DEFAULT 'person' CHECK (proposed_via IN ('person','advisor')),
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected','withdrawn')),
  decided_by    TEXT,
  decided_at    timestamptz,
  decision_note TEXT,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT engine_config_proposals_not_self_approved
    CHECK (decided_by IS NULL OR status <> 'approved' OR decided_by <> proposed_by)
);
CREATE INDEX IF NOT EXISTS idx_engine_config_proposals_tenant_status
  ON engine_config_proposals (tenant_id, status, created_at DESC);

-- Buying signals customers expressed in their own words, found by the signal
-- sweep over masked transcripts. No quote is stored: the evidence is a
-- reference to the transcript turn (and a span in it), rendered on read, so a
-- later redaction reaches it. Sensitive categories are never written.
CREATE TABLE IF NOT EXISTS customer_signals (
  id                TEXT PRIMARY KEY,
  tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id       TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  interaction_id    TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  transcript_turn_id TEXT REFERENCES interaction_transcript(id) ON DELETE SET NULL,
  channel           TEXT NOT NULL,
  signal_code       TEXT NOT NULL CHECK (signal_code IN (
    'vehicle_purchase','home_purchase','home_renovation','new_job_or_raise',
    'business_expansion','marriage','child_education','travel','insurance_need',
    'credit_limit_need','high_interest_debt','gold_holding','product_interest',
    'not_interested')),
  product_hint      TEXT,
  horizon           TEXT CHECK (horizon IS NULL OR horizon IN ('now','this_month','this_quarter','later','unknown')),
  confidence        NUMERIC(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  extractor_version INTEGER NOT NULL,
  feedback          TEXT CHECK (feedback IS NULL OR feedback IN ('right','wrong')),
  feedback_by       TEXT,
  feedback_at       timestamptz,
  superseded_at     timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_signals_customer
  ON customer_signals (tenant_id, customer_id, created_at DESC) WHERE superseded_at IS NULL;

-- One row per interaction the sweep has judged, at which extractor version,
-- and why it was skipped when it was: "never analysed" and "analysed, found
-- nothing" and "not allowed to analyse" are three different answers.
CREATE TABLE IF NOT EXISTS signal_scans (
  interaction_id    TEXT PRIMARY KEY REFERENCES interactions(id) ON DELETE CASCADE,
  tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id       TEXT REFERENCES customers_pii(id) ON DELETE CASCADE,
  extractor_version INTEGER NOT NULL,
  status            TEXT NOT NULL CHECK (status IN ('claimed','done','skipped','failed')),
  skip_reason       TEXT,
  signals           INTEGER NOT NULL DEFAULT 0,
  scanned_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signal_scans_tenant ON signal_scans (tenant_id, scanned_at DESC);

-- A lead raised by the promotional sender, tied to the offer decision that
-- chose it, so the lead's outcome labels that decision.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS decision_id TEXT;
CREATE INDEX IF NOT EXISTS idx_leads_decision ON leads (decision_id) WHERE decision_id IS NOT NULL;
