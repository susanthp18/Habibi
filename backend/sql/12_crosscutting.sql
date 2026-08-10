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
-- Identity is (endpoint, key): callers scope replay lookups by both, so a
-- global PK on `key` alone silently dropped the second endpoint's stored
-- response and let the replay execute as a fresh write.
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (endpoint, key)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_endpoint ON idempotency_keys(endpoint);

-- ---------------------------------------------------------------------------
-- Bot runtime queues (migrations 20260722_0025 / 20260724_0030).
-- Postgres FOR UPDATE SKIP LOCKED is the broker; these tables ARE the queue, so
-- a base schema without them leaves the WhatsApp bot unable to run at all.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bot_turn_jobs (
  id TEXT PRIMARY KEY,
  -- ON DELETE CASCADE (migration 20260726_0042): conversations already cascade
  -- from customers/interactions, so a NO ACTION reference here aborted a
  -- customer erasure with a foreign-key violation part-way through.
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
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

-- Shared KB rate-limit counters (kb_rate_limit). Process-local windows let an
-- N-replica deployment serve N× the configured limit; this makes the cap apply
-- to the deployment and isolates tenants from each other.
CREATE TABLE IF NOT EXISTS kb_rate_limit_counters (
  bucket TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  window_start timestamptz NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket, tenant_id, window_start)
);
CREATE INDEX IF NOT EXISTS idx_kb_rate_limit_counters_window
  ON kb_rate_limit_counters (window_start);

-- conversations.bot_state (migration 20260722_0025) — bot runtime turn state.
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS bot_state jsonb NOT NULL DEFAULT '{}'::jsonb;

-- messages.bot_turn_job_id (migration 20260722_0025 / FK added in 20260725_0040).
-- Declared here rather than in 04_interactions.sql because bot_turn_jobs does
-- not exist yet at that point in the base-schema load order.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS bot_turn_job_id TEXT;
DO $$
BEGIN
  ALTER TABLE messages
    ADD CONSTRAINT fk_messages_bot_turn_job
    FOREIGN KEY (bot_turn_job_id) REFERENCES bot_turn_jobs(id) ON DELETE SET NULL;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
-- One outbound message per bot turn job.
CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_bot_turn_job_id
  ON messages (bot_turn_job_id)
  WHERE bot_turn_job_id IS NOT NULL;

-- Every CRM tool call, on any channel. job_id/conversation_id are nullable
-- because they only exist on the WhatsApp/text path — a voice tool call has an
-- interaction and a transcript turn instead, and before those columns existed
-- voice tool calls were simply never recorded. The CHECK preserves the
-- invariant that actually mattered: a row must be attributable to something.
CREATE TABLE IF NOT EXISTS bot_tool_calls (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES bot_turn_jobs(id) ON DELETE CASCADE,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE CASCADE,
  -- SET NULL, not CASCADE: a redaction sweep that removes a transcript turn
  -- must not also remove the record that a CRM tool ran.
  transcript_turn_id TEXT REFERENCES interaction_transcript(id) ON DELETE SET NULL,
  channel TEXT,
  tool_name TEXT NOT NULL,
  args jsonb NOT NULL DEFAULT '{}'::jsonb,
  result_ok BOOLEAN NOT NULL DEFAULT true,
  error TEXT,
  result_preview TEXT,
  latency_ms INTEGER,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_bot_tool_calls_attribution
    CHECK (job_id IS NOT NULL OR interaction_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_job
  ON bot_tool_calls (job_id, created_at);
CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_conversation
  ON bot_tool_calls (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_turn
  ON bot_tool_calls (transcript_turn_id);
CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_interaction
  ON bot_tool_calls (interaction_id, created_at);

CREATE TABLE IF NOT EXISTS whatsapp_outbound_jobs (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES messages(id),
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
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
  post_attempted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_whatsapp_outbound_jobs_status CHECK (
    status IN ('queued','running','succeeded','failed','dead')
  )
);
CREATE INDEX IF NOT EXISTS ix_whatsapp_outbound_jobs_status_run_after
  ON whatsapp_outbound_jobs (status, run_after, created_at);
CREATE INDEX IF NOT EXISTS ix_whatsapp_outbound_jobs_conversation_status
  ON whatsapp_outbound_jobs (conversation_id, status);
-- One outbound send per message row — replays must not double-send.
CREATE UNIQUE INDEX IF NOT EXISTS uq_whatsapp_outbound_jobs_message_id
  ON whatsapp_outbound_jobs (message_id);


-- ---------------------------------------------------------------------------
-- Live voice session bind (migration 20260726_0045). That revision creates this
-- table with a raw op.execute, which the CI drift check (it regexes
-- op.create_table / op.add_column) cannot see -- so the mirror was never made
-- and a fresh sql/-built database had no voice_sessions at all. Without it
-- persist.start_voice_call fails, the exception is swallowed on connect, and
-- every CRM tool returns no_interaction / identity_not_verified.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_sessions (
  id              TEXT PRIMARY KEY,
  interaction_id  TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  deployment_id   TEXT REFERENCES bot_deployments(id),
  transport       TEXT NOT NULL
    CHECK (transport IN ('smallwebrtc','twilio','daily')),
  provider_call_id TEXT,
  worker_host     TEXT,
  status          TEXT NOT NULL
    CHECK (status IN ('starting','live','ending','ended','failed')),
  started_at      timestamptz,
  ended_at        timestamptz,
  last_heartbeat_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
-- Partial unique: only one live session per provider call, but many rows may
-- legitimately have no provider_call_id (SmallWebRTC sandbox sessions).
CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_sessions_provider_call_id
  ON voice_sessions (provider_call_id)
  WHERE provider_call_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_voice_sessions_interaction_id
  ON voice_sessions (interaction_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_status
  ON voice_sessions (status);
