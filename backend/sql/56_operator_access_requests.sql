-- Access requests: a signed-in operator who cannot open a page can ask an
-- admin for a role, with a reason. Fresh installs pick this up via the sql/ glob.

CREATE TABLE IF NOT EXISTS operator_access_requests (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  page_path TEXT NOT NULL,
  permission TEXT,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','denied')),
  granted_role_id TEXT REFERENCES roles(id),
  requested_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  reviewed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  last_error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_operator_access_requests_tenant_id
  ON operator_access_requests(tenant_id);
CREATE INDEX IF NOT EXISTS idx_operator_access_requests_status
  ON operator_access_requests(tenant_id, status, requested_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_operator_access_requests_pending_page
  ON operator_access_requests (tenant_id, user_id, page_path)
  WHERE status = 'pending';

ALTER TABLE operator_access_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_access_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON operator_access_requests;
CREATE POLICY tenant_isolation ON operator_access_requests
  FOR ALL
  USING (operator_access_requests.tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (operator_access_requests.tenant_id = current_setting('app.tenant_id', true));
