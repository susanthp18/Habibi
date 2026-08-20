CREATE TABLE IF NOT EXISTS redaction_rule_configs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pii_type TEXT NOT NULL,
  replacement TEXT NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_redaction_rule_configs_tenant_id ON redaction_rule_configs(tenant_id);

CREATE TABLE IF NOT EXISTS redaction_records (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL UNIQUE REFERENCES interactions(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  reviewed boolean NOT NULL DEFAULT false,
  reviewed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_redaction_records_customer_id ON redaction_records(customer_id);

CREATE TABLE IF NOT EXISTS pii_findings (
  id TEXT PRIMARY KEY,
  redaction_id TEXT NOT NULL REFERENCES redaction_records(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('card','pan','phone','email','address','dob','account','ifsc','aadhaar','custom')),
  masked TEXT NOT NULL,
  confidence numeric(5,3),
  accepted boolean NOT NULL DEFAULT false,
  transcript_turn_id TEXT REFERENCES interaction_transcript(id) ON DELETE SET NULL,
  start_offset INTEGER,
  end_offset INTEGER,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pii_findings_redaction_id ON pii_findings(redaction_id);

CREATE TABLE IF NOT EXISTS redaction_audio_segments (
  id TEXT PRIMARY KEY,
  redaction_id TEXT NOT NULL REFERENCES redaction_records(id) ON DELETE CASCADE,
  media_id TEXT NOT NULL REFERENCES interaction_media(id) ON DELETE CASCADE,
  finding_id TEXT REFERENCES pii_findings(id) ON DELETE SET NULL,
  at_sec INTEGER NOT NULL,
  duration_sec INTEGER NOT NULL,
  muted boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_redaction_audio_segments_redaction_id ON redaction_audio_segments(redaction_id);

CREATE TABLE IF NOT EXISTS export_jobs (
  id TEXT PRIMARY KEY,
  -- Whose data was exported, not who clicked export. actor_user_id is
  -- attribution and ON DELETE SET NULL (migration 0062).
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  format TEXT NOT NULL,
  scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  watermark TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  storage_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_export_jobs_tenant_id ON export_jobs(tenant_id);

CREATE TABLE IF NOT EXISTS export_job_records (
  export_job_id TEXT NOT NULL REFERENCES export_jobs(id) ON DELETE CASCADE,
  redaction_id TEXT NOT NULL REFERENCES redaction_records(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (export_job_id, redaction_id)
);

