CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_fields (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  field_key TEXT NOT NULL,
  label TEXT NOT NULL,
  secret boolean NOT NULL DEFAULT false,
  required boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_configs (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  values jsonb NOT NULL DEFAULT '{}'::jsonb,
  health TEXT,
  latency_ms INTEGER,
  enabled boolean NOT NULL DEFAULT true,
  credential_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_config_versions (
  id TEXT PRIMARY KEY,
  config_id TEXT NOT NULL REFERENCES provider_configs(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  values jsonb NOT NULL DEFAULT '{}'::jsonb,
  changed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS integration_test_logs (
  id TEXT PRIMARY KEY,
  config_id TEXT NOT NULL REFERENCES provider_configs(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  payload_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhook_endpoints (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  target_system TEXT NOT NULL,
  -- Operator-facing label (migration 20260724_0031).
  name TEXT,
  url TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','paused','broken')),
  signing_algorithm TEXT,
  secret_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhook_endpoint_headers (
  id TEXT PRIMARY KEY,
  endpoint_id TEXT NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
  header_key TEXT NOT NULL,
  header_value TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhook_retry_policies (
  id TEXT PRIMARY KEY,
  endpoint_id TEXT NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
  max_attempts INTEGER NOT NULL,
  backoff_strategy TEXT NOT NULL,
  max_event_age_sec INTEGER NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_types (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
  endpoint_id TEXT NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
  event_type_id TEXT NOT NULL REFERENCES event_types(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (endpoint_id, event_type_id)
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id TEXT PRIMARY KEY,
  endpoint_id TEXT NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
  event_type_id TEXT NOT NULL REFERENCES event_types(id),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  response_body TEXT,
  http_status INTEGER,
  attempt_number INTEGER NOT NULL DEFAULT 1,
  latency_ms INTEGER,
  status TEXT NOT NULL CHECK (status IN ('success','client_err','server_err','pending')),
  next_retry_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);

CREATE TABLE IF NOT EXISTS billing_services (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  unit TEXT NOT NULL,
  unit_cost_inr numeric(14,4) NOT NULL,
  provider TEXT NOT NULL DEFAULT 'Unknown',
  category TEXT NOT NULL DEFAULT 'Infra' CHECK (category IN ('LLM','Voice','Messaging','Infra')),
  color TEXT NOT NULL DEFAULT '#64748b',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing_usage_daily (
  id TEXT PRIMARY KEY,
  service_id TEXT NOT NULL REFERENCES billing_services(id),
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  usage_date date NOT NULL,
  units numeric(14,4) NOT NULL,
  cost_inr numeric(14,2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (service_id, tenant_id, environment, usage_date)
);
CREATE INDEX IF NOT EXISTS idx_billing_usage_daily_tenant_id ON billing_usage_daily(tenant_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_daily_date ON billing_usage_daily(usage_date);

CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  invoice_month TEXT NOT NULL,
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  total_inr numeric(14,2) NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  issued_at date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoice_line_items (
  id TEXT PRIMARY KEY,
  invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  service_id TEXT NOT NULL REFERENCES billing_services(id),
  units numeric(14,4) NOT NULL,
  unit_cost_inr numeric(14,4) NOT NULL,
  amount_inr numeric(14,2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budgets (
  id TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
  environment TEXT NOT NULL DEFAULT 'production' CHECK (environment IN ('sandbox','production')),
  month TEXT NOT NULL,
  amount_inr numeric(14,2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_org_env_month
  ON budgets (environment, month) WHERE tenant_id IS NULL;

CREATE TABLE IF NOT EXISTS budget_rules (
  id TEXT PRIMARY KEY,
  budget_id TEXT NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
  threshold_pct numeric(6,2) NOT NULL,
  action_channel TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warn' CHECK (severity IN ('info','warn','critical')),
  action TEXT NOT NULL DEFAULT 'Notify',
  channels JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budget_alert_events (
  id TEXT PRIMARY KEY,
  budget_rule_id TEXT NOT NULL REFERENCES budget_rules(id) ON DELETE CASCADE,
  triggered_at timestamptz NOT NULL DEFAULT now(),
  spend_inr numeric(14,2) NOT NULL,
  message TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS usage_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  service_id TEXT NOT NULL REFERENCES billing_services(id),
  units numeric(18,6) NOT NULL,
  cost_inr numeric(14,6) NOT NULL,
  meta JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  source_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_service_env
  ON usage_events (service_id, tenant_id, environment, occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_occurred ON usage_events (occurred_at DESC);

