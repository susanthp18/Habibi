-- Entra identity on operator users, plus the default Viewer role.
--
-- Fresh installs get the columns from sql/01_identity.sql. This file is the
-- additive path for databases that already ran 01. No email/UPN backfill:
-- oid is bound on first successful token, not guessed from seed names.

ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_oid UUID;
ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_tid UUID;
ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_upn TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bootstrap_admin boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_entra_oid ON users (entra_oid) WHERE entra_oid IS NOT NULL;

-- One Viewer row, same global-id pattern as role-admin. Unconfigured: the
-- enforcer falls back to authz.ROLE_DEFAULTS["viewer"] until someone saves.
INSERT INTO roles (id, tenant_id, name)
SELECT 'role-viewer', t.id, 'Viewer'
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id = 'role-viewer')
ORDER BY t.created_at
LIMIT 1;
