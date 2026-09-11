-- Object-level reach and raw-PII access are grants, not role names.
--
-- visibility.resolve decided "which customers" from the role's *name*
-- (supervisor -> team, qa_reviewer/compliance_officer/dpo -> all) and
-- db_redaction let Admin/Compliance/DPO read unredacted findings the same way.
-- A renamed role silently changed its reach, and the Roles screen could not
-- move it. These three permissions carry it now; the defaults below match what
-- the names used to grant, keyed on the normalised role name so an existing
-- role with explicit rows keeps the reach it had.

INSERT INTO permissions (id, module, action, description) VALUES
  (
    'perm-customers-read-team', 'customers', 'read_team',
    'See the customers of every agent on the teams you supervise'
  ),
  (
    'perm-customers-read-all', 'customers', 'read_all',
    'See every customer in the tenant (oversight roles)'
  ),
  (
    'perm-pii-raw-read', 'compliance', 'raw_pii',
    'Read unredacted PII inside compliance findings'
  )
ON CONFLICT (id) DO UPDATE SET
  module = EXCLUDED.module,
  action = EXCLUDED.action,
  description = EXCLUDED.description;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.permission_id
  FROM roles r
  JOIN (
    VALUES
      ('admin',               'perm-customers-read-team'),
      ('admin',               'perm-customers-read-all'),
      ('admin',               'perm-pii-raw-read'),
      ('supervisor',          'perm-customers-read-team'),
      ('manager',             'perm-customers-read-team'),
      ('qa_reviewer',         'perm-customers-read-all'),
      ('compliance_officer',  'perm-customers-read-all'),
      ('compliance_officer',  'perm-pii-raw-read'),
      ('dpo',                 'perm-customers-read-all'),
      ('dpo',                 'perm-pii-raw-read')
  ) AS p(role_name, permission_id)
    ON lower(replace(replace(r.name, '-', '_'), ' ', '_')) = p.role_name
 -- Only roles that already carry explicit rows: an unconfigured role with none
 -- falls back to authz.ROLE_DEFAULTS, which grants the same.
 WHERE EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.id)
ON CONFLICT DO NOTHING;
