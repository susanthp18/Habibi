-- Per-user authoring MCP credentials. Never used for dialling or PayInt data MCP.
-- Mirrors alembic/versions/20260926_0164_voice_studio_mcp_keys.py.
CREATE TABLE IF NOT EXISTS voice_studio_mcp_keys (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  key_prefix TEXT NOT NULL,
  scopes TEXT[] NOT NULL CHECK (array_length(scopes, 1) BETWEEN 1 AND 2),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at timestamptz,
  rotated_from TEXT REFERENCES voice_studio_mcp_keys(id)
);
CREATE INDEX IF NOT EXISTS idx_voice_studio_mcp_keys_owner
  ON voice_studio_mcp_keys(tenant_id, user_id, created_at DESC);
