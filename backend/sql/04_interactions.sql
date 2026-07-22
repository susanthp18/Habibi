CREATE TABLE IF NOT EXISTS interactions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  handler_kind TEXT NOT NULL CHECK (handler_kind IN ('human','bot')),
  handler_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  handler_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  transferred_from_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  direction TEXT CHECK (direction IN ('inbound','outbound')),
  status TEXT NOT NULL CHECK (status IN ('active','completed','abandoned','failed')),
  disposition TEXT,
  primary_intent TEXT,
  query_resolved boolean NOT NULL DEFAULT false,
  upsell_presented boolean NOT NULL DEFAULT false,
  ptp_captured boolean NOT NULL DEFAULT false,
  avg_sentiment numeric(5,3),
  sentiment_label TEXT CHECK (sentiment_label IN ('positive','neutral','negative')),
  summary TEXT,
  hash TEXT,
  latency_ms INTEGER,
  rag_hits INTEGER NOT NULL DEFAULT 0,
  redaction_applied boolean NOT NULL DEFAULT false,
  deployment_id TEXT,
  started_at timestamptz,
  ended_at timestamptz,
  duration_sec INTEGER,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (handler_kind='human' AND handler_user_id IS NOT NULL AND handler_bot_id IS NULL)
    OR (handler_kind='bot' AND handler_bot_id IS NOT NULL AND handler_user_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_interactions_tenant_id ON interactions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_interactions_customer_id ON interactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_interactions_account_id ON interactions(account_id);
CREATE INDEX IF NOT EXISTS idx_interactions_status ON interactions(status);
CREATE INDEX IF NOT EXISTS idx_interactions_started_at ON interactions(started_at);

CREATE TABLE IF NOT EXISTS interaction_participants (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  participant_kind TEXT NOT NULL CHECK (participant_kind IN ('customer','human','bot','supervisor')),
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  role TEXT NOT NULL CHECK (role IN ('primary','customer','monitor','whisper','barge')),
  joined_at timestamptz,
  left_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    participant_kind='customer'
    OR (participant_kind IN ('human','supervisor') AND user_id IS NOT NULL AND bot_id IS NULL)
    OR (participant_kind='bot' AND bot_id IS NOT NULL AND user_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_interaction_participants_interaction_id ON interaction_participants(interaction_id);

CREATE TABLE IF NOT EXISTS interaction_handoffs (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  from_kind TEXT NOT NULL CHECK (from_kind IN ('human','bot')),
  from_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  from_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  to_kind TEXT NOT NULL CHECK (to_kind IN ('human','bot')),
  to_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  to_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  to_team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
  reason TEXT NOT NULL CHECK (reason IN ('sentiment_drop','verification_failed','compliance','customer_requested','hardship','dispute','high_value','routing_rule')),
  queue TEXT,
  requested_at timestamptz,
  accepted_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interaction_handoffs_interaction_id ON interaction_handoffs(interaction_id);

CREATE TABLE IF NOT EXISTS interaction_transcript (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  turn_index INTEGER NOT NULL,
  speaker TEXT NOT NULL,
  at_sec INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL,
  sentiment_delta numeric(5,3),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (interaction_id, turn_index)
);
CREATE INDEX IF NOT EXISTS idx_interaction_transcript_interaction_id ON interaction_transcript(interaction_id);

CREATE TABLE IF NOT EXISTS interaction_sentiment (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  at_sec INTEGER NOT NULL,
  score numeric(5,3) NOT NULL,
  label TEXT CHECK (label IN ('positive','neutral','negative')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interaction_sentiment_interaction_id ON interaction_sentiment(interaction_id);

CREATE TABLE IF NOT EXISTS interaction_flags (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  flag TEXT NOT NULL,
  severity TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interaction_flags_interaction_id ON interaction_flags(interaction_id);

CREATE TABLE IF NOT EXISTS interaction_disclosures (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  rule_id TEXT,
  label TEXT NOT NULL,
  read_at_sec INTEGER,
  read_by_kind TEXT CHECK (read_by_kind IN ('human','bot')),
  read_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  read_by_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  read boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interaction_disclosures_interaction_id ON interaction_disclosures(interaction_id);

CREATE TABLE IF NOT EXISTS interaction_media (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('audio','voicemail','transcript_export','redacted_audio','waveform')),
  storage_ref TEXT NOT NULL,
  duration_sec INTEGER,
  mime_type TEXT NOT NULL,
  size_bytes bigint,
  hash TEXT,
  waveform_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interaction_media_interaction_id ON interaction_media(interaction_id);

CREATE TABLE IF NOT EXISTS identity_verifications (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  method TEXT NOT NULL CHECK (method IN ('phone_match','dob','otp','account_tail','manual')),
  status TEXT NOT NULL CHECK (status IN ('pending','verified','failed')),
  attempt_count INTEGER NOT NULL DEFAULT 1,
  verified_at timestamptz,
  failure_reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_identity_verifications_interaction_id ON identity_verifications(interaction_id);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  assigned_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('bot','needs_human','escalated','assigned')),
  channel TEXT NOT NULL CHECK (channel IN ('whatsapp','sms','email','chat')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_interaction_id ON conversations(interaction_id);
CREATE INDEX IF NOT EXISTS idx_conversations_customer_id ON conversations(customer_id);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender TEXT NOT NULL CHECK (sender IN ('customer','bot','agent','system')),
  body TEXT NOT NULL,
  delivery_status TEXT,
  provider_ref TEXT,
  sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);

CREATE TABLE IF NOT EXISTS canned_responses (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
  label TEXT NOT NULL,
  body TEXT NOT NULL,
  channel TEXT CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  enabled boolean NOT NULL DEFAULT true,
  created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_canned_responses_tenant_id ON canned_responses(tenant_id);

CREATE TABLE IF NOT EXISTS ai_response_suggestions (
  id TEXT PRIMARY KEY,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE CASCADE,
  transcript_turn_id TEXT REFERENCES interaction_transcript(id) ON DELETE CASCADE,
  suggestion_text TEXT NOT NULL,
  source TEXT,
  accepted boolean,
  accepted_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((conversation_id IS NOT NULL)::int + (interaction_id IS NOT NULL)::int + (transcript_turn_id IS NOT NULL)::int >= 1)
);
CREATE INDEX IF NOT EXISTS idx_ai_response_suggestions_interaction_id ON ai_response_suggestions(interaction_id);

CREATE TABLE IF NOT EXISTS live_alerts (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('sentiment_drop','compliance','long_hold','escalation','silence','loop_detected')),
  severity TEXT NOT NULL DEFAULT 'medium',
  reason TEXT,
  acknowledged_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  acknowledged_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_live_alerts_interaction_id ON live_alerts(interaction_id);

CREATE TABLE IF NOT EXISTS supervisor_actions (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  supervisor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('listen_in','whisper','barge','force_handoff')),
  target_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  target_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  note TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_supervisor_actions_interaction_id ON supervisor_actions(interaction_id);

