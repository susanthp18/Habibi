CREATE TABLE IF NOT EXISTS analytics_daily (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  metric_date date NOT NULL,
  resolved_calls INTEGER NOT NULL DEFAULT 0,
  escalations INTEGER NOT NULL DEFAULT 0,
  ptp_count INTEGER NOT NULL DEFAULT 0,
  avg_sentiment numeric(5,3),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analytics_daily_tenant_id ON analytics_daily(tenant_id);

CREATE TABLE IF NOT EXISTS intent_aggregates (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  metric_date date NOT NULL,
  intent TEXT NOT NULL,
  sessions INTEGER NOT NULL DEFAULT 0,
  containment_rate numeric(7,4),
  escalation_rate numeric(7,4),
  abandonment_rate numeric(7,4),
  avg_turns numeric(8,2),
  avg_latency_ms INTEGER,
  avg_sentiment numeric(5,3),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS escalation_reasons (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  reason TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  trend numeric(8,4),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS unanswered_questions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  hit_count INTEGER NOT NULL DEFAULT 0,
  last_seen_at timestamptz,
  suggested_fix_type TEXT,
  top_intent TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics_kb_gap_links (
  id TEXT PRIMARY KEY,
  unanswered_question_id TEXT NOT NULL REFERENCES unanswered_questions(id) ON DELETE CASCADE,
  kb_document_id TEXT REFERENCES kb_documents(id) ON DELETE SET NULL,
  faq_pair_id TEXT REFERENCES faq_pairs(id) ON DELETE SET NULL,
  prompt_version_id TEXT REFERENCES prompt_versions(id) ON DELETE SET NULL,
  routing_rule_id TEXT REFERENCES routing_rules(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

