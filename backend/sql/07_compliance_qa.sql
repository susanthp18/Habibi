CREATE TABLE IF NOT EXISTS compliance_rules (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- A regulator's rule code is unique *within* a bank, not across banks. As a
  -- bare UNIQUE on code it was global: two tenants citing the same regulation
  -- would collide, and only the first could hold the row (migration 0062).
  CONSTRAINT ux_compliance_rules_tenant_code UNIQUE (tenant_id, code)
);
CREATE INDEX IF NOT EXISTS idx_compliance_rules_tenant_id ON compliance_rules(tenant_id);

CREATE TABLE IF NOT EXISTS violations (
  id TEXT PRIMARY KEY,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  rule_id TEXT NOT NULL REFERENCES compliance_rules(id),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','bot')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  actor_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','in_review','acknowledged','resolved')),
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  description TEXT,
  at_sec INTEGER NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (actor_kind='human' AND actor_user_id IS NOT NULL AND actor_bot_id IS NULL)
    OR (actor_kind='bot' AND actor_bot_id IS NOT NULL AND actor_user_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_violations_interaction_id ON violations(interaction_id);
CREATE INDEX IF NOT EXISTS idx_violations_customer_id ON violations(customer_id);

CREATE TABLE IF NOT EXISTS qa_rubrics (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_rubrics_tenant_id ON qa_rubrics(tenant_id);

CREATE TABLE IF NOT EXISTS qa_rubric_sections (
  id TEXT PRIMARY KEY,
  rubric_id TEXT NOT NULL REFERENCES qa_rubrics(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  weight numeric(7,4) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_rubric_sections_rubric_id ON qa_rubric_sections(rubric_id);

CREATE TABLE IF NOT EXISTS qa_rubric_criteria (
  id TEXT PRIMARY KEY,
  section_id TEXT NOT NULL REFERENCES qa_rubric_sections(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  description TEXT,
  weight numeric(7,4) NOT NULL,
  critical_fail boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_rubric_criteria_section_id ON qa_rubric_criteria(section_id);

CREATE TABLE IF NOT EXISTS qa_scorecards (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL UNIQUE REFERENCES interactions(id) ON DELETE CASCADE,
  rubric_id TEXT NOT NULL REFERENCES qa_rubrics(id),
  subject_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  subject_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  reviewer_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'unscored',
  total_score numeric(6,2),
  band TEXT,
  scored_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_scorecards_interaction_id ON qa_scorecards(interaction_id);

CREATE TABLE IF NOT EXISTS qa_scorecard_entries (
  id TEXT PRIMARY KEY,
  scorecard_id TEXT NOT NULL REFERENCES qa_scorecards(id) ON DELETE CASCADE,
  criterion_id TEXT NOT NULL REFERENCES qa_rubric_criteria(id),
  ai_suggested_score numeric(6,2),
  final_score numeric(6,2),
  note TEXT,
  accepted boolean,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_scorecard_entries_scorecard_id ON qa_scorecard_entries(scorecard_id);

CREATE TABLE IF NOT EXISTS coaching_actions (
  id TEXT PRIMARY KEY,
  -- Explicit tenant: subject_user_id / interaction_id are all nullable, so
  -- there is no join that reliably scopes a coaching action to its tenant.
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  subject_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  subject_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  scorecard_id TEXT REFERENCES qa_scorecards(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'General',
  -- Screen vocabulary (migration 20260722_0022 retired open/pending/new).
  status TEXT NOT NULL DEFAULT 'assigned'
    CONSTRAINT ck_coaching_actions_status CHECK (status IN ('assigned','in_progress','done')),
  due_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_coaching_actions_tenant_id ON coaching_actions(tenant_id);

CREATE TABLE IF NOT EXISTS calibration_sessions (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  rubric_id TEXT NOT NULL REFERENCES qa_rubrics(id),
  name TEXT,
  target_scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Screen vocabulary (migration 20260722_0022 retired open/pending/new).
  status TEXT NOT NULL DEFAULT 'active'
    CONSTRAINT ck_calibration_sessions_status CHECK (status IN ('active','closed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Append-only live FPC log (P7). Every failing turn is written, including
-- shadow runs that never took the call. A log holding only the barges we
-- executed has no negative class.
CREATE TABLE IF NOT EXISTS live_qa_decisions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  mode TEXT NOT NULL,
  feature_schema_version TEXT NOT NULL,
  features jsonb NOT NULL DEFAULT '{}'::jsonb,
  verdict TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  reason TEXT,
  reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
  findings jsonb NOT NULL DEFAULT '[]'::jsonb,
  latency_ms INTEGER,
  enacted boolean NOT NULL DEFAULT false,
  enacted_at timestamptz,
  enacted_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_live_qa_decisions_mode CHECK (mode IN ('off','shadow','live')),
  CONSTRAINT ck_live_qa_decisions_verdict CHECK (verdict IN ('pass','fail_soft','fail_critical')),
  CONSTRAINT ck_live_qa_decisions_action CHECK (
    recommended_action IN ('none','listen','whisper','barge','inbox')
  )
);
CREATE INDEX IF NOT EXISTS idx_live_qa_decisions_tenant_id ON live_qa_decisions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_live_qa_decisions_interaction
  ON live_qa_decisions (interaction_id, created_at DESC)
  WHERE interaction_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS calibration_reviewer_scores (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES calibration_sessions(id) ON DELETE CASCADE,
  reviewer_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes TEXT,
  variance_from_target numeric(6,2),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- compliance_scans — ledger of what the rule catalog has judged.
--
-- Detection used to run once, live, inside a bot voice call, and left no
-- record of what had been evaluated. Without that, "no violation" and "never
-- checked" are the same row, and a rule change can only ever apply going
-- forward. Storing the rules version per interaction makes a rule change a
-- backfill: bump it and every interaction re-enters the sweep queue.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance_scans (
  interaction_id TEXT PRIMARY KEY REFERENCES interactions(id) ON DELETE CASCADE,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  rules_version  INTEGER NOT NULL,
  findings       INTEGER NOT NULL DEFAULT 0,
  scanned_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_compliance_scans_version
  ON compliance_scans (rules_version, scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_compliance_scans_tenant
  ON compliance_scans (tenant_id);
