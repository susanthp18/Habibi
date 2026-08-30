CREATE TABLE IF NOT EXISTS kb_documents (
  id TEXT PRIMARY KEY,
  -- Ownership. updated_by_user_id below is attribution and ON DELETE SET NULL,
  -- so it cannot carry tenancy: 20 of 21 rows had it NULL, and deleting a user
  -- would have moved their documents out of the tenant (migration 0062).
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  type TEXT NOT NULL CHECK (type IN ('policy','sop','product','compliance','faq','benefits')),
  version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','indexing','indexed','stale','failed')),
  enabled boolean NOT NULL DEFAULT true,
  chunk_size INTEGER,
  chunk_overlap INTEGER,
  title TEXT NOT NULL,
  tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  embedding_model TEXT,
  last_indexed_at timestamptz,
  product_key TEXT,
  source_path TEXT,
  content_hash TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_documents_product_key ON kb_documents(product_key);
CREATE INDEX IF NOT EXISTS idx_kb_documents_tenant_id ON kb_documents(tenant_id);

CREATE TABLE IF NOT EXISTS kb_source_files (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  storage_ref TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes bigint,
  hash TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_source_files_document_id ON kb_source_files(document_id);

CREATE TABLE IF NOT EXISTS kb_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  heading TEXT,
  tokens INTEGER,
  text TEXT NOT NULL,
  embedding vector(1536),
  hits INTEGER NOT NULL DEFAULT 0,
  chunk_index INTEGER NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id ON kb_chunks(document_id);
-- UNIQUE: (document_id, chunk_index) identifies a chunk. Duplicates were
-- reachable if an interrupted _atomic_replace_chunks left old rows behind, and
-- retrieval then returned the same passage twice with divergent embeddings.
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_document_id_chunk_index
  ON kb_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_hnsw
  ON kb_chunks USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

-- `attempt` bounds stuck-job reclaim: a job that keeps dying mid-run is moved
-- to 'dead' instead of being re-queued forever (see kb_ingest.reclaim_stuck_jobs).
CREATE TABLE IF NOT EXISTS kb_index_jobs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','dead')),
  attempt INTEGER NOT NULL DEFAULT 0,
  chunk_size INTEGER,
  chunk_overlap INTEGER,
  embedding_model TEXT,
  started_at timestamptz,
  completed_at timestamptz,
  error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_snapshots (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  faq_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_snapshots_tenant_id ON kb_snapshots(tenant_id);

CREATE TABLE IF NOT EXISTS faq_pairs (
  id TEXT PRIMARY KEY,
  linked_document_id TEXT REFERENCES kb_documents(id) ON DELETE SET NULL,
  intent TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  embedding vector(1536),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_faq_pairs_embedding_hnsw
  ON faq_pairs USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS prompt_versions (
  id TEXT PRIMARY KEY,
  -- The bank the prompt was written for — not the current employer of its
  -- author, which is what author_user_id would have implied (migration 0062).
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  -- Which mouth this version belongs to. A fleet is one published row per bot
  -- (migration 20260815_0073); the previous unique was per tenant, which made
  -- a second card impossible.
  bot_id TEXT NOT NULL REFERENCES bots(id),
  author_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','published','archived')),
  prompt TEXT NOT NULL,
  persona jsonb NOT NULL DEFAULT '{}'::jsonb,
  voice jsonb NOT NULL DEFAULT '{}'::jsonb,
  guardrails jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Authored conversation graph (see backend/flow_graph.py). Empty object means
  -- "no authored flow" — the runtime then uses the hardcoded voice/flows.py.
  -- Lives here so it versions and publishes atomically with the prompt whose
  -- node instructions it contains.
  flow jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Agent Card: skills, tools, handoffs, locked policy engines. Mouth columns
  -- above stay canonical; the card references them rather than duplicating.
  agent_card jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- AgentTuning saved with the version (migration 20260723_0029). This column
  -- was added by that migration and never mirrored here, so until now a fresh
  -- sql/-built database was missing a column the Prompt Studio writes to.
  tuning jsonb NOT NULL DEFAULT '{}'::jsonb,
  label TEXT,
  summary TEXT NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_tenant_id ON prompt_versions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_bot_id ON prompt_versions(bot_id);
-- At most one published prompt version per bot. The previous unique was
-- (tenant_id) WHERE published — a fleet cannot exist under that rule.
CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_versions_one_published_per_bot
  ON prompt_versions (bot_id)
  WHERE status = 'published';

CREATE TABLE IF NOT EXISTS tts_voices (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  name TEXT NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tts_voices_tenant_id ON tts_voices(tenant_id);

CREATE TABLE IF NOT EXISTS tts_price_tiers (
  tier text PRIMARY KEY,
  label text NOT NULL,
  approx_usd_per_1m_chars numeric,
  is_premium boolean NOT NULL DEFAULT false,
  notes text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- tts_voice_catalog.price_tier FKs here, so EVERY tier derive_price_tier() can
-- return must exist before the catalog sync runs. Seeding only 'standard' left
-- hd / hd_flash / turbo to migrations 0043-0044, which a fresh install stamps
-- rather than replays: the boot sync then inserted all 774 voices in one
-- executemany, the first DragonHD voice raised
-- tts_voice_catalog_price_tier_fkey, and the whole batch rolled back. The
-- catalog sat empty, and every voice looked "missing from the catalog" to
-- db.get_tts_voice_warning -- which rewrites the selection to the fallback, so
-- picking any voice in the Studio silently played en-IN-AartiNeural.
INSERT INTO tts_price_tiers (tier, label, approx_usd_per_1m_chars, is_premium, notes)
VALUES
  ('standard', 'Standard neural', 15.0, false, 'Default tier for catalog voices'),
  ('hd',       'Neural HD',       30.0, true,  'HD / Multilingual neural voices'),
  ('hd_flash', 'Neural HD Flash', 22.0, true,  'HD Flash neural voices'),
  ('turbo',    'Turbo / AOAI',    NULL, true,  'Rare turbo / AOAI voices')
ON CONFLICT (tier) DO NOTHING;

CREATE TABLE IF NOT EXISTS tts_voice_catalog (
  short_name text PRIMARY KEY,
  display_name text NOT NULL,
  local_name text NOT NULL DEFAULT '',
  gender text NOT NULL DEFAULT 'Neutral',
  locale text NOT NULL,
  locale_name text NOT NULL DEFAULT '',
  voice_type text NOT NULL DEFAULT 'Neural',
  status text NOT NULL DEFAULT 'GA',
  sample_rate_hertz integer,
  words_per_minute integer,
  styles jsonb NOT NULL DEFAULT '[]'::jsonb,
  model_series jsonb NOT NULL DEFAULT '[]'::jsonb,
  personalities jsonb NOT NULL DEFAULT '[]'::jsonb,
  scenarios jsonb NOT NULL DEFAULT '[]'::jsonb,
  price_tier text NOT NULL DEFAULT 'standard' REFERENCES tts_price_tiers(tier),
  is_premium boolean NOT NULL DEFAULT false,
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  removed_at timestamptz,
  enabled_for_picker boolean NOT NULL DEFAULT true,
  -- Which vendor this voice came from. The FK lands in 90_deferred_fks.sql:
  -- providers is layer 10 and this table is layer 09, so the reference is
  -- forward at CREATE time.
  provider_id text
);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_locale ON tts_voice_catalog (locale);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_provider ON tts_voice_catalog (provider_id);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_price_tier ON tts_voice_catalog (price_tier);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_gender ON tts_voice_catalog (gender);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_status ON tts_voice_catalog (status);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_premium ON tts_voice_catalog (is_premium);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_removed ON tts_voice_catalog (removed_at);

CREATE TABLE IF NOT EXISTS tts_voice_sync_runs (
  id text PRIMARY KEY,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  source text NOT NULL CHECK (source IN ('azure', 'json_import', 'admin')),
  fetched_count integer NOT NULL DEFAULT 0,
  upserted integer NOT NULL DEFAULT 0,
  soft_removed integer NOT NULL DEFAULT 0,
  unchanged integer NOT NULL DEFAULT 0,
  error text,
  region text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tts_voice_sync_runs_started ON tts_voice_sync_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS persona_presets (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_persona_presets_tenant_id ON persona_presets(tenant_id);

CREATE TABLE IF NOT EXISTS bot_deployments (
  id TEXT PRIMARY KEY,
  bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id),
  kb_snapshot_id TEXT REFERENCES kb_snapshots(id),
  tts_voice_id TEXT,  -- Azure Speech ShortName (e.g. en-IN-AartiNeural); not FK'd to tts_voices
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  status TEXT NOT NULL CHECK (status IN ('active','rolled_back','retired')),
  published_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  published_at timestamptz,
  rollback_deployment_id TEXT REFERENCES bot_deployments(id) ON DELETE SET NULL,
  voice_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- AgentTuning (§4.7) — LLM/TTS/STT/VAD/turn/interaction knobs; default-filled by migration 0028.
  tuning jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Canary fields. Phase 1 writes traffic_pct=100, shadow=false only; split
  -- traffic is Phase 5. eval_report_id is the compiler artifact that blocked
  -- or allowed this publish (nullable for versions that predate evals).
  traffic_pct INTEGER NOT NULL DEFAULT 100 CHECK (traffic_pct BETWEEN 0 AND 100),
  shadow boolean NOT NULL DEFAULT false,
  eval_report_id TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bot_deployments_bot_id ON bot_deployments(bot_id);
-- At most one active deployment per bot+environment (enforced also by advisory lock on publish).
CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_deployments_bot_env_active
  ON bot_deployments (bot_id, environment)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS routing_rules (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  priority INTEGER NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  name TEXT NOT NULL DEFAULT '',
  description TEXT,
  category TEXT,
  conditions jsonb NOT NULL DEFAULT '[]'::jsonb,
  action_key TEXT NOT NULL,
  action_params jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sandbox_scenarios (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  sim_persona jsonb NOT NULL DEFAULT '{}'::jsonb,
  turns jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sandbox_scenarios_tenant_id ON sandbox_scenarios(tenant_id);

CREATE TABLE IF NOT EXISTS sandbox_runs (
  id TEXT PRIMARY KEY,
  scenario_id TEXT REFERENCES sandbox_scenarios(id) ON DELETE SET NULL,
  deployment_id TEXT REFERENCES bot_deployments(id) ON DELETE SET NULL,
  prompt_version_id TEXT REFERENCES prompt_versions(id) ON DELETE SET NULL,
  kb_snapshot_id TEXT REFERENCES kb_snapshots(id) ON DELETE SET NULL,
  started_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
  aggregate_latency_ms INTEGER,
  aggregate_tokens INTEGER,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sandbox_run_turns (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES sandbox_runs(id) ON DELETE CASCADE,
  turn_index INTEGER NOT NULL,
  speaker TEXT NOT NULL,
  text TEXT NOT NULL,
  detected_intent TEXT,
  sentiment_label TEXT CHECK (sentiment_label IN ('positive','neutral','negative')),
  retrieved_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  guardrail_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
  latency_ms INTEGER,
  token_count INTEGER,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_logs (
  id TEXT PRIMARY KEY,
  -- All three links below are optional and 127 of 214 rows had none of them
  -- set, so this table needs its own tenant rather than one inherited from a
  -- parent that may not exist (migration 0062).
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  sandbox_run_id TEXT REFERENCES sandbox_runs(id) ON DELETE SET NULL,
  -- Which turn asked. interaction_id alone is session-grained, so "which
  -- retrieval backed turn 4's answer" was unanswerable.
  transcript_turn_id TEXT REFERENCES interaction_transcript(id) ON DELETE SET NULL,
  query TEXT NOT NULL,
  top_chunks jsonb NOT NULL DEFAULT '[]'::jsonb,
  latency_ms INTEGER,
  selected_answer_source TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_retrieval_logs_interaction_id ON retrieval_logs(interaction_id);
CREATE INDEX IF NOT EXISTS ix_retrieval_logs_turn ON retrieval_logs(transcript_turn_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_logs_tenant_id ON retrieval_logs(tenant_id);

CREATE TABLE IF NOT EXISTS routing_rule_executions (
  id TEXT PRIMARY KEY,
  rule_id TEXT REFERENCES routing_rules(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  sandbox_run_id TEXT REFERENCES sandbox_runs(id) ON DELETE SET NULL,
  context jsonb NOT NULL DEFAULT '{}'::jsonb,
  result TEXT,
  action_taken TEXT,
  evaluated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_routing_rule_executions_interaction_id ON routing_rule_executions(interaction_id);

-- Sandbox Live voice session config, shared between the API process (which
-- writes it on POST /voice/sandbox/start) and the voice worker (which reads it
-- when the WebRTC offer arrives). These are separate containers, so a local
-- JSON file was invisible to the reader. See backend/voice_session_store.py.
CREATE TABLE IF NOT EXISTS voice_sandbox_sessions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_voice_sandbox_sessions_tenant_id ON voice_sandbox_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_sandbox_sessions_updated_at ON voice_sandbox_sessions(updated_at);

-- Persona presets. These lived only in migration 0018, which a fresh install
-- stamps rather than replays -- so a newly seeded database had an empty table
-- and the Studio's Presets panel fell back to hardcoded frontend copies of
-- rows that did not exist. Same drift class as the price tiers above.
--
-- The templates interpolate only SYSTEM_SAFE_VARIABLES. CRM fields reach the
-- model on the untrusted context card; a {customer_name} here never resolves,
-- and the line carrying it is dropped before the model sees it.

INSERT INTO persona_presets (id, tenant_id, name, config) VALUES
  ('compliance', 'hdfc', 'Compliance-First', '{"label": "Compliance-First", "traits": {"upsell": 5, "empathy": 55, "firmness": 55, "formality": 90, "verbosity": 55}, "description": "Every disclosure, every time", "promptTemplate": "You are {agent_name}, a compliance-first collections agent for {bank_name}.\nVerify the caller''s identity before sharing any account information.\nAccount details are in the CRM context card and may only be discussed after verification succeeds.\nSpeak in {language}. Keep to the script; if a request falls outside policy, say so plainly and escalate.\nNever quote an interest rate, waiver or settlement figure that a tool has not returned."}'::jsonb)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
  config = EXCLUDED.config, updated_at = now();
INSERT INTO persona_presets (id, tenant_id, name, config) VALUES
  ('empathetic', 'hdfc', 'Empathetic Collector', '{"label": "Empathetic Collector", "traits": {"upsell": 20, "empathy": 82, "firmness": 40, "formality": 55, "verbosity": 60}, "description": "Warm, patient, hardship-aware", "promptTemplate": "You are {agent_name}, an inbound collections voice agent for {bank_name}.\nGreet the caller warmly and acknowledge their situation before discussing dues.\nTheir account number, outstanding balance and due date arrive in the CRM context card — quote those figures verbatim and never invent one.\nSpeak in {language}. Be patient, empathetic and non-judgemental.\nNever threaten legal action. Offer Promise-to-Pay options when the caller signals hardship."}'::jsonb)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
  config = EXCLUDED.config, updated_at = now();
INSERT INTO persona_presets (id, tenant_id, name, config) VALUES
  ('firm', 'hdfc', 'Firm Collector', '{"label": "Firm Collector", "traits": {"upsell": 15, "empathy": 35, "firmness": 80, "formality": 65, "verbosity": 40}, "description": "Direct, outcome-focused", "promptTemplate": "You are {agent_name}, a collections agent for {bank_name}.\nAddress the caller directly and state the purpose of the call within the first two sentences.\nState the overdue amount and due date from the CRM context card, exactly as given. Never estimate or round them.\nSpeak in {language}. Be concise and outcome-focused; ask for a specific payment date.\nNever threaten legal action and never imply consequences the bank has not authorised."}'::jsonb)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
  config = EXCLUDED.config, updated_at = now();
INSERT INTO persona_presets (id, tenant_id, name, config) VALUES
  ('upsell', 'hdfc', 'Upsell-Focused', '{"label": "Upsell-Focused", "traits": {"upsell": 75, "empathy": 65, "firmness": 45, "formality": 55, "verbosity": 55}, "description": "Resolve, then convert", "promptTemplate": "You are {agent_name}, a collections and relationship voice agent for {bank_name}.\nResolve the caller''s query about their overdue balance first — the figures are in the CRM context card.\nOnly once the collections matter is settled and sentiment is not negative, mention at most one offer returned by recommend_next_offer.\nSpeak in {language}. Never name a product the tool did not give you."}'::jsonb)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
  config = EXCLUDED.config, updated_at = now();
