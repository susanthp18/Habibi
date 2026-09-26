-- Viewer is the Entra first-login role. Org presenters must be able to open
-- every read surface of the seeded book. Writes, voice, and admin stay off.
-- seed_postgres.py inserts the same set from authz.ROLE_DEFAULTS; this file
-- is the additive path for a database that already ran the narrower grants.

INSERT INTO role_permissions (role_id, permission_id)
SELECT 'role-viewer', permission_id
FROM unnest(ARRAY[
  'perm-customers-read',
  'perm-customers-read-all',
  'perm-interactions-read',
  'perm-collections-read',
  'perm-leads-read',
  'perm-consent-read',
  'perm-analytics-read',
  'perm-billing-read',
  'perm-qa-review',
  'perm-compliance-read',
  'perm-policy-read',
  'perm-subject-rights-read',
  'perm-bank-boundary-read',
  'perm-kb-read',
  'perm-bot-read',
  'perm-supervisor-read',
  'perm-integrations-read'
]) AS permission_id
WHERE EXISTS (SELECT 1 FROM roles WHERE id = 'role-viewer')
  -- The catalogue is upserted at API boot (authz.ensure_permission_catalog),
  -- so on an empty database these rows do not exist yet and the grant broke
  -- the whole sql/ build on its foreign key. Skip what is not there; the seed
  -- and ROLE_DEFAULTS grant the same set once the catalogue is in.
  AND EXISTS (SELECT 1 FROM permissions p WHERE p.id = permission_id)
ON CONFLICT DO NOTHING;
