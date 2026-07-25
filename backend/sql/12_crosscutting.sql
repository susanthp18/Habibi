CREATE TABLE IF NOT EXISTS activity_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  actor_kind TEXT CHECK (actor_kind IN ('human','bot','system','customer')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  actor_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  note TEXT,
  tone TEXT,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activity_events_entity ON activity_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_activity_events_tenant_id ON activity_events(tenant_id);

CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(id) ON DELETE SET NULL,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_id ON audit_log(tenant_id);

-- Replay guard for mutating endpoints and bot tool writes (migration
-- 20260721_0002). Without this table every idempotent write silently degrades
-- to a duplicate insert, so it must exist in the base schema too.
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  endpoint TEXT NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_endpoint ON idempotency_keys(endpoint);

-- ---------------------------------------------------------------------------
-- Bot runtime queues (migrations 20260722_0025 / 20260724_0030).
-- Postgres FOR UPDATE SKIP LOCKED is the broker; these tables ARE the queue, so
-- a base schema without them leaves the WhatsApp bot unable to run at all.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bot_turn_jobs (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  interaction_id TEXT REFERENCES interactions(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  trigger_message_id TEXT REFERENCES messages(id),
  trigger_provider_ref TEXT,
  channel TEXT NOT NULL DEFAULT 'whatsapp',
  attempt INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'queued',
  superseded_by_job_id TEXT,
  outbound_message_id TEXT,
  error TEXT,
  locked_at timestamptz,
  locked_by TEXT,
  run_after timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bot_turn_jobs_status CHECK (
    status IN ('queued','running','succeeded','failed','dead','superseded','cancelled')
  ),
  CONSTRAINT ck_bot_turn_jobs_channel CHECK (channel IN ('whatsapp','sandbox','voice'))
);
CREATE INDEX IF NOT EXISTS ix_bot_turn_jobs_status_run_after
  ON bot_turn_jobs (status, run_after, created_at);
CREATE INDEX IF NOT EXISTS ix_bot_turn_jobs_conversation
  ON bot_turn_jobs (conversation_id, status);
-- Inbound idempotency: one job per WhatsApp wamid (Meta retries).
CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_turn_jobs_trigger_provider_ref
  ON bot_turn_jobs (trigger_provider_ref)
  WHERE trigger_provider_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS bot_tool_calls (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES bot_turn_jobs(id),
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  tool_name TEXT NOT NULL,
  args jsonb NOT NULL DEFAULT '{}'::jsonb,
  result_ok BOOLEAN NOT NULL DEFAULT true,
  error TEXT,
  result_preview TEXT,
  latency_ms INTEGER,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_job
  ON bot_tool_calls (job_id, created_at);
CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_conversation
  ON bot_tool_calls (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS whatsapp_outbound_jobs (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES messages(id),
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  customer_id TEXT REFERENCES customers(id),
  to_phone TEXT NOT NULL,
  body TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'queued',
  error TEXT,
  provider_ref TEXT,
  locked_at timestamptz,
  locked_by TEXT,
  run_after timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_whatsapp_outbound_jobs_status CHECK (
    status IN ('queued','running','succeeded','failed','dead')
  )
);
CREATE INDEX IF NOT EXISTS ix_whatsapp_outbound_jobs_status_run_after
  ON whatsapp_outbound_jobs (status, run_after, created_at);
-- One outbound send per message row — replays must not double-send.
CREATE UNIQUE INDEX IF NOT EXISTS uq_whatsapp_outbound_jobs_message_id
  ON whatsapp_outbound_jobs (message_id);

