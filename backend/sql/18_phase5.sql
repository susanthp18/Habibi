-- Phase 5: canary experiments, A2A partners/tasks. No OPA import. No Temporal.

CREATE TABLE IF NOT EXISTS deployment_experiments (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  canary_deployment_id TEXT NOT NULL REFERENCES bot_deployments(id) ON DELETE CASCADE,
  baseline_deployment_id TEXT REFERENCES bot_deployments(id) ON DELETE SET NULL,
  traffic_pct INTEGER NOT NULL CHECK (traffic_pct BETWEEN 0 AND 100),
  shadow boolean NOT NULL DEFAULT false,
  auto_rollback jsonb NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL CHECK (status IN ('running','rolled_back','promoted')),
  rollback_reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_deployment_experiments_running
  ON deployment_experiments (tenant_id, bot_id, environment)
  WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_deployment_experiments_bot
  ON deployment_experiments (bot_id, status);

CREATE TABLE IF NOT EXISTS a2a_partners (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  card_url TEXT NOT NULL,
  cert_fingerprint TEXT NOT NULL,
  cert_dn TEXT,
  allowed_skills TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','disabled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, cert_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_a2a_partners_tenant ON a2a_partners(tenant_id);

CREATE TABLE IF NOT EXISTS a2a_tasks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  partner_id TEXT REFERENCES a2a_partners(id) ON DELETE SET NULL,
  bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  skill_id TEXT,
  status TEXT NOT NULL DEFAULT 'submitted'
    CHECK (status IN (
      'submitted','working','input-required','completed','failed','cancelled'
    )),
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  output jsonb NOT NULL DEFAULT '{}'::jsonb,
  cert_dn TEXT,
  error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_tenant_status
  ON a2a_tasks(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_partner ON a2a_tasks(partner_id);
