-- Release history of each PayInt Voice Studio agent: every publish and rollback,
-- who did it and the changelog note they wrote.
-- Mirrors alembic/versions/20260926_0163_voice_studio_releases.py.
--
-- The engine keeps the versions themselves (workflow definitions); this table
-- is PayInt's changelog on top, written by /voice-studio/agents/{id}/publish and
-- /rollback (routers/voice_studio_admin.py).

CREATE TABLE IF NOT EXISTS voice_studio_releases (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  engine_workflow_id INTEGER NOT NULL,
  version_number INTEGER,
  from_version INTEGER,
  action TEXT NOT NULL CHECK (action IN ('publish', 'rollback')),
  note TEXT NOT NULL CHECK (length(btrim(note)) > 0),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_voice_studio_releases_tenant_id ON voice_studio_releases(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_studio_releases_agent
  ON voice_studio_releases(tenant_id, engine_workflow_id, created_at DESC);
