-- Durable intent before an engine release; replay and fresh installs use this file.
CREATE TABLE IF NOT EXISTS voice_studio_release_attempts (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  engine_workflow_id INTEGER NOT NULL,
  engine_definition_id INTEGER NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('publish', 'rollback')),
  from_version INTEGER,
  intended_version INTEGER,
  result_version INTEGER,
  note TEXT NOT NULL,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_studio_release_attempts_active
  ON voice_studio_release_attempts(tenant_id, engine_workflow_id, engine_definition_id, action)
  WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_voice_studio_release_attempts_pending
  ON voice_studio_release_attempts(tenant_id, engine_workflow_id)
  WHERE status = 'pending';
