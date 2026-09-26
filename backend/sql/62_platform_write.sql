-- perm-platform-write: writing the tenant-less rows every tenant reads.
-- Mirrors the grant half of alembic/versions/20260925_0158_platform_scope_rls.py;
-- the policy half is derived (scripts/rls.py apply), as in 0126.
--
-- Statutory rule sets and the platform budget have tenant_id NULL. Row security
-- lets every tenant read them and none write them, except inside
-- platform_scope.enter, which requires this permission. Admin is a superuser by
-- name already; the row keeps the stored grants equal to authz.ROLE_DEFAULTS.

INSERT INTO permissions (id, module, action, description) VALUES
  (
    'perm-platform-write', 'platform', 'write',
    'Change platform-wide records every tenant reads: statutory rule sets and the platform budget'
  )
ON CONFLICT (id) DO UPDATE SET
  module = EXCLUDED.module,
  action = EXCLUDED.action,
  description = EXCLUDED.description;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, 'perm-platform-write'
  FROM roles r
 WHERE lower(replace(replace(r.name, '-', '_'), ' ', '_')) = 'admin'
   -- Only roles already carrying explicit rows; an unconfigured one falls back
   -- to authz.ROLE_DEFAULTS, which grants the same.
   AND EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.id)
ON CONFLICT DO NOTHING;
