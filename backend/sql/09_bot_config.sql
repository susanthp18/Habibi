CREATE TABLE IF NOT EXISTS kb_documents (
  id TEXT PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id_chunk_index ON kb_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_hnsw
  ON kb_chunks USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS kb_index_jobs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed')),
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
  label TEXT NOT NULL,
  document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  faq_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

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
  author_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','published','archived')),
  prompt TEXT NOT NULL,
  persona jsonb NOT NULL DEFAULT '{}'::jsonb,
  voice jsonb NOT NULL DEFAULT '{}'::jsonb,
  guardrails jsonb NOT NULL DEFAULT '{}'::jsonb,
  label TEXT,
  summary TEXT NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_versions_one_published
  ON prompt_versions ((status))
  WHERE status = 'published';

CREATE TABLE IF NOT EXISTS tts_voices (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  name TEXT NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tts_price_tiers (
  tier text PRIMARY KEY,
  label text NOT NULL,
  approx_usd_per_1m_chars numeric,
  is_premium boolean NOT NULL DEFAULT false,
  notes text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);

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
  enabled_for_picker boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_locale ON tts_voice_catalog (locale);
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
  name TEXT NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bot_deployments (
  id TEXT PRIMARY KEY,
  bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id),
  kb_snapshot_id TEXT REFERENCES kb_snapshots(id),
  tts_voice_id TEXT REFERENCES tts_voices(id),
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production')),
  status TEXT NOT NULL CHECK (status IN ('active','rolled_back','retired')),
  published_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  published_at timestamptz,
  rollback_deployment_id TEXT REFERENCES bot_deployments(id) ON DELETE SET NULL,
  voice_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- AgentTuning (§4.7) — LLM/TTS/STT/VAD/turn/interaction knobs; default-filled by migration 0028.
  tuning jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bot_deployments_bot_id ON bot_deployments(bot_id);

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
  name TEXT NOT NULL,
  sim_persona jsonb NOT NULL DEFAULT '{}'::jsonb,
  turns jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

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
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  sandbox_run_id TEXT REFERENCES sandbox_runs(id) ON DELETE SET NULL,
  query TEXT NOT NULL,
  top_chunks jsonb NOT NULL DEFAULT '[]'::jsonb,
  latency_ms INTEGER,
  selected_answer_source TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_retrieval_logs_interaction_id ON retrieval_logs(interaction_id);

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
