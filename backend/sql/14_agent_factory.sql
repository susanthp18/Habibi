-- Agent factory tables (Phase 1). Eval reports are compiler artifacts attached
-- to a deployment; context_summaries bound voice token growth off the audio path.

CREATE TABLE IF NOT EXISTS eval_suites (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  -- `outbound` covers the failure modes that are invisible until a campaign
  -- is already running: pitching to a voicemail, confirming a debt to a
  -- spouse, honouring an opt-out a tick late. Compile gate G-OB9 blocks an
  -- outbound publish without a passing report from one of these.
  kind TEXT NOT NULL CHECK (kind IN ('regression','capability','redteam','twin','outbound')),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eval_suites_tenant_id ON eval_suites(tenant_id);
CREATE INDEX IF NOT EXISTS idx_eval_suites_kind ON eval_suites(kind);

CREATE TABLE IF NOT EXISTS eval_tasks (
  id TEXT PRIMARY KEY,
  suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  grader TEXT NOT NULL,
  fixture jsonb NOT NULL DEFAULT '{}'::jsonb,
  pass_bar TEXT NOT NULL DEFAULT 'all',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eval_tasks_suite_id ON eval_tasks(suite_id);

CREATE TABLE IF NOT EXISTS eval_redteam_cases (
  id TEXT PRIMARY KEY,
  suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  attack TEXT NOT NULL,
  fixture jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eval_redteam_cases_suite_id ON eval_redteam_cases(suite_id);

CREATE TABLE IF NOT EXISTS eval_reports (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  suite_id TEXT NOT NULL REFERENCES eval_suites(id),
  bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  prompt_version_id TEXT REFERENCES prompt_versions(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('pass','fail','error')),
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eval_reports_tenant_id ON eval_reports(tenant_id);
CREATE INDEX IF NOT EXISTS idx_eval_reports_suite_id ON eval_reports(suite_id);

CREATE TABLE IF NOT EXISTS eval_trials (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES eval_reports(id) ON DELETE CASCADE,
  task_id TEXT REFERENCES eval_tasks(id) ON DELETE SET NULL,
  redteam_case_id TEXT REFERENCES eval_redteam_cases(id) ON DELETE SET NULL,
  k INTEGER NOT NULL DEFAULT 1,
  passed boolean NOT NULL,
  transcript jsonb NOT NULL DEFAULT '[]'::jsonb,
  tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
  crm_outcomes jsonb NOT NULL DEFAULT '{}'::jsonb,
  grader_verdicts jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eval_trials_report_id ON eval_trials(report_id);

CREATE TABLE IF NOT EXISTS context_summaries (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  upto_turn INTEGER NOT NULL,
  summary TEXT NOT NULL,
  model_profile TEXT NOT NULL DEFAULT 'analysis',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (interaction_id, upto_turn)
);
CREATE INDEX IF NOT EXISTS idx_context_summaries_tenant_id ON context_summaries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_context_summaries_interaction_id ON context_summaries(interaction_id);

DROP TRIGGER IF EXISTS trg_eval_suites_updated_at ON eval_suites;
CREATE TRIGGER trg_eval_suites_updated_at
  BEFORE UPDATE ON eval_suites
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
