-- Operator invites: branded email to Microsoft sign-in, with a starting role
-- applied on first login only. Fresh installs pick this up via the sql/ glob.

CREATE TABLE IF NOT EXISTS operator_invites (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  role_id TEXT NOT NULL REFERENCES roles(id),
  invited_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','revoked')),
  sent_at timestamptz NOT NULL DEFAULT now(),
  accepted_at timestamptz,
  last_error TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_operator_invites_tenant_id ON operator_invites(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_operator_invites_pending_email
  ON operator_invites (tenant_id, lower(email))
  WHERE status = 'pending';

-- Same tenant policy rls.py derives for any rooted table. Fresh installs
-- that apply sql/ without a later `rls.py enable` would otherwise boot with
-- the hardening gate's missing=1 on this table.
ALTER TABLE operator_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_invites FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON operator_invites;
CREATE POLICY tenant_isolation ON operator_invites
  FOR ALL
  USING (operator_invites.tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (operator_invites.tenant_id = current_setting('app.tenant_id', true));
