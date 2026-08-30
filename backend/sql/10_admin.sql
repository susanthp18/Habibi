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
-- One config row per provider per tenant per environment. This is the upsert
-- conflict target: keying on the surrogate id alone let one tenant's write
-- clobber another tenant's row when ids collided.
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_configs_provider_tenant_env
  ON provider_configs (provider_id, tenant_id, environment);

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

-- The capability matrix. A provider is not uniformly good — Azure has ~20 Arabic
-- voices and weak Arabic recognition; Deepgram is fast everywhere and does no
-- Arabic code-switching. Recording capability per (provider, kind, model) is
-- what lets binding be a per-locale decision instead of a per-product one.
CREATE TABLE IF NOT EXISTS provider_models (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('stt','tts','llm')),
  model_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  -- Fully-qualified Pipecat service class. Stored, not derived: the runtime
  -- must not guess a class name from a provider slug.
  service_class TEXT NOT NULL,
  locales TEXT[] NOT NULL DEFAULT '{}',
  streaming boolean NOT NULL DEFAULT true,
  -- True only for models handling a language change INSIDE one sentence.
  -- Language-ID routing does not qualify and must not claim it.
  code_switch boolean NOT NULL DEFAULT false,
  on_prem boolean NOT NULL DEFAULT false,
  diarization boolean NOT NULL DEFAULT false,
  styles TEXT[] NOT NULL DEFAULT '{}',
  cost_per_unit numeric(12,6),
  cost_unit TEXT CHECK (cost_unit IN ('usd_per_1m_chars','usd_per_hour','usd_per_1m_tokens')),
  -- OUR measurements against OUR audio. NULL means unmeasured, which is an
  -- honest state a vendor's published number would have silently overwritten.
  measured_latency_p50_ms INTEGER,
  measured_latency_p95_ms INTEGER,
  measured_at timestamptz,
  notes TEXT NOT NULL DEFAULT '',
  -- The controls this model actually honours, as a JSON array of
  -- descriptors the UI renders generically. Azure has style/rate/pitch;
  -- Fish S2.1 Pro has temperature/top_p/repetition_penalty and no pitch
  -- at all. Rendering one provider's knobs for another is a control that
  -- silently does nothing. Each entry carries a `transport` (body|ssml)
  -- so a knob with nowhere to go cannot be shipped as decoration.
  params_schema jsonb NOT NULL DEFAULT '[]'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_models_provider_kind_model
  ON provider_models (provider_id, kind, model_id);
CREATE INDEX IF NOT EXISTS idx_provider_models_kind
  ON provider_models (kind) WHERE enabled;

-- Which provider serves which slot, for whom. Resolved most-specific-first:
--   (bot, locale) → (bot, any) → (tenant, locale) → (tenant, any)
-- `priority` orders the failover chain WITHIN one specificity, which is why
-- this is a table and not a column: a column holds the choice but not the
-- fallback. Resolution returning nothing is an error the caller handles — a
-- silent default is the exact bug this table exists to remove.
CREATE TABLE IF NOT EXISTS agent_provider_bindings (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE,
  slot TEXT NOT NULL CHECK (slot IN ('stt','tts','llm')),
  locale TEXT,
  provider_model_id TEXT NOT NULL REFERENCES provider_models(id) ON DELETE RESTRICT,
  voice_ref TEXT,
  priority INTEGER NOT NULL DEFAULT 100,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- bot_id and locale are nullable and both carry identity, so uniqueness must
-- COALESCE them: a plain multi-column unique index treats every NULL as
-- distinct and would allow two conflicting defaults for the same slot.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_provider_bindings_slot
  ON agent_provider_bindings (
    tenant_id, COALESCE(bot_id, ''), slot, COALESCE(locale, ''), priority
  );
CREATE INDEX IF NOT EXISTS idx_agent_provider_bindings_lookup
  ON agent_provider_bindings (tenant_id, slot, enabled);

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
  secret_hash TEXT,
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
  -- 'pending' + next_retry_at are the queue webhooks_dispatch drains. There is
  -- no separate jobs table: a delivery IS the unit of work, and its attempt
  -- chain is one row whose attempt_number climbs, so the log an operator reads
  -- and the queue the worker claims from cannot drift apart.
  next_retry_at timestamptz,
  -- Claim bookkeeping, same convention as whatsapp_outbound_jobs, so a worker
  -- that dies mid-POST leaves a row the next one can reclaim rather than a row
  -- that is stuck 'pending' forever with nobody holding it.
  locked_at timestamptz,
  locked_by TEXT,
  -- 'simulated' is the Integrations test-fire button, which does no egress.
  -- It stays for demos, but it is labelled: a simulated 200 that reads like a
  -- real delivery is how this system spent its whole life lying.
  delivery_mode TEXT NOT NULL DEFAULT 'live'
             CHECK (delivery_mode IN ('live','simulated')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_claim
  ON webhook_deliveries(status, next_retry_at);

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
  -- Scale matches usage_events: the flusher adds each batch into these columns,
  -- so anything narrower rounds on every flush and a sub-paisa batch rounds to
  -- zero outright. The error is systematically downward, and these are the
  -- columns the billing screens read.
  units numeric(18,6) NOT NULL,
  cost_inr numeric(14,6) NOT NULL,
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
-- Org-wide rows (tenant_id IS NULL) and tenant rows each need their own
-- partial unique index: a single index over (tenant_id, environment, month)
-- would not constrain the NULL-tenant rows at all.
CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_org_env_month
  ON budgets (environment, month) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_tenant_env_month
  ON budgets (tenant_id, environment, month) WHERE tenant_id IS NOT NULL;

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
  -- Free-form provenance ("which code path emitted this"). Not an id: call
  -- attribution lives in interaction_id below.
  source_ref TEXT,
  -- SET NULL, not CASCADE: a retention sweep that deletes an interaction must
  -- not delete the record that money was spent.
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  model TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_service_env
  ON usage_events (service_id, tenant_id, environment, occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_occurred ON usage_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_interaction
  ON usage_events (interaction_id) WHERE interaction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_usage_events_model
  ON usage_events (service_id, model, occurred_at) WHERE model IS NOT NULL;


-- Operator-flippable runtime switches.
--
-- The outbound engine's gates (TREATMENT_MODE, CAMPAIGN_RUNTIME_ENABLED,
-- BOUNCE_VOICE_ENABLED) are environment variables, so turning dialling off
-- means editing .env and restarting four processes. That is not a control an
-- operator can reach during an incident, and it is not one a demo can rely on.
--
-- Absence is OFF. A missing row, a wiped table and a failed read all mean the
-- same thing, so a fresh install does not dial and neither does a broken one.
-- The switch is the last word: it is checked at the carrier boundary, so no
-- caller — present or future — can route around it.
CREATE TABLE IF NOT EXISTS platform_switches (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  -- Who flipped it and when. A kill switch with no attribution is an argument
  -- waiting to happen.
  updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  note TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, key)
);
