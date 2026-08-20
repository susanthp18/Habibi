-- Phase 3: vault refs, scoped MCP keys, connectors, long-running MCP tasks.
-- Triggers live here (sql/13 runs before this file).

CREATE TABLE IF NOT EXISTS vault_refs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL
    CHECK (purpose IN ('llm','twilio','whatsapp','mcp_key','connector_oauth','webhook','other')),
  backend TEXT NOT NULL DEFAULT 'local'
    CHECK (backend IN ('local','azure')),
  azure_secret_name TEXT,
  ciphertext TEXT,
  last_rotated_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_vault_refs_tenant ON vault_refs(tenant_id);

CREATE TABLE IF NOT EXISTS mcp_keys (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL,
  key_prefix TEXT NOT NULL,
  scopes TEXT[] NOT NULL DEFAULT '{}',
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mcp_keys_tenant ON mcp_keys(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mcp_keys_hash ON mcp_keys(key_hash) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS mcp_connectors (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  display_name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('first_party','remote_mcp')),
  url TEXT,
  auth_ref TEXT REFERENCES vault_refs(id) ON DELETE SET NULL,
  allow_prefixes TEXT[] NOT NULL DEFAULT '{}',
  data_class TEXT[] NOT NULL DEFAULT '{}',
  ttl_ms INTEGER NOT NULL DEFAULT 30000,
  timeout_ms INTEGER NOT NULL DEFAULT 2500,
  circuit_fails INTEGER NOT NULL DEFAULT 0,
  circuit_opened_at timestamptz,
  allowed_env TEXT NOT NULL DEFAULT 'sandbox'
    CHECK (allowed_env IN ('sandbox','production','both')),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','approved','disabled')),
  health TEXT NOT NULL DEFAULT 'unknown'
    CHECK (health IN ('unknown','healthy','degraded','down')),
  last_tools_list_at timestamptz,
  tools_cache JSONB NOT NULL DEFAULT '[]'::jsonb,
  cimd_issuer TEXT,
  cimd_client_id TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_mcp_connectors_tenant ON mcp_connectors(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mcp_connectors_status ON mcp_connectors(status);

CREATE TABLE IF NOT EXISTS mcp_tasks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','succeeded','failed')),
  customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mcp_tasks_tenant_status ON mcp_tasks(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_mcp_tasks_customer ON mcp_tasks(customer_id);

DROP TRIGGER IF EXISTS trg_vault_refs_updated_at ON vault_refs;
CREATE TRIGGER trg_vault_refs_updated_at
  BEFORE UPDATE ON vault_refs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_mcp_keys_updated_at ON mcp_keys;
CREATE TRIGGER trg_mcp_keys_updated_at
  BEFORE UPDATE ON mcp_keys
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_mcp_connectors_updated_at ON mcp_connectors;
CREATE TRIGGER trg_mcp_connectors_updated_at
  BEFORE UPDATE ON mcp_connectors
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_mcp_tasks_updated_at ON mcp_tasks;
CREATE TRIGGER trg_mcp_tasks_updated_at
  BEFORE UPDATE ON mcp_tasks
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
