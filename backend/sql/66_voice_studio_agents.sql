-- Which PayInt Voice Studio agent runs each outbound objective.
-- Mirrors alembic/versions/20260926_0162_voice_studio_agents.py.
--
-- Voice Studio (the voice-agent engine) owns the conversation; our treatment,
-- cadence and campaign engines still decide who is called and why. When
-- outbound.place dials through the `studio` telephony provider, the attempt's
-- objective picks the engine agent here ('*' is the tenant's default), and the
-- agent is started through its API trigger path.

CREATE TABLE IF NOT EXISTS voice_studio_agents (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  objective TEXT NOT NULL CHECK (length(btrim(objective)) > 0),
  engine_workflow_id INTEGER NOT NULL,
  trigger_path TEXT NOT NULL CHECK (length(btrim(trigger_path)) > 0),
  label TEXT,
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, objective)
);
CREATE INDEX IF NOT EXISTS idx_voice_studio_agents_tenant_id ON voice_studio_agents(tenant_id);

-- Guardrails for each Voice Studio agent (engine workflow). The engine runs the
-- conversation; these are PayInt's rules, checked on every bot turn of its
-- calls and WhatsApp threads (voice_studio.flag_turns): prohibited phrases,
-- never quote a rate, never promise a waiver, legal-threat escalation, turn cap.
-- No row = the platform defaults in voice_studio.DEFAULT_GUARDRAILS.
CREATE TABLE IF NOT EXISTS voice_studio_guardrails (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  engine_workflow_id INTEGER NOT NULL,
  guardrails JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(guardrails) = 'object'),
  updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, engine_workflow_id)
);
CREATE INDEX IF NOT EXISTS idx_voice_studio_guardrails_tenant_id ON voice_studio_guardrails(tenant_id);

-- Scripted rehearsals of an engine agent, graded against its guardrails
-- (voice_studio_checks.py). One row per run; results holds each scenario's
-- conversation and flags.
CREATE TABLE IF NOT EXISTS voice_studio_checks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  engine_workflow_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done')),
  passed INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  results JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_voice_studio_checks_tenant_id ON voice_studio_checks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_studio_checks_agent ON voice_studio_checks(tenant_id, engine_workflow_id, created_at DESC);
