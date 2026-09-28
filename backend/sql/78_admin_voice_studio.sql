-- Settings, Roles & access and Billing wired to Voice Studio. Additive; row
-- security for the new table comes from scripts/rls.py like every tenant table.

-- The handsets a test call may ring, and the engine's own test-call allow-list
-- (voice_studio.test_numbers). Staff phones, not borrower PII.
CREATE TABLE IF NOT EXISTS test_numbers (
  id                TEXT PRIMARY KEY,
  tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  e164              TEXT NOT NULL CHECK (e164 ~ '^\+[0-9]{8,15}$'),
  label             TEXT,
  added_by_user_id  TEXT,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, e164)
);

-- The demo button's number becomes a test number wherever a customer holds it,
-- so an existing demo keeps working on the first day.
INSERT INTO test_numbers (id, tenant_id, e164, label)
SELECT DISTINCT ON (c.tenant_id) 'TN-demo-' || c.tenant_id, c.tenant_id, '+919655282324', 'Demo handset'
FROM customers c
WHERE regexp_replace(COALESCE(c.phone_primary, ''), '\D', '', 'g') IN ('919655282324', '9655282324')
ON CONFLICT DO NOTHING;

-- Voice Studio's maker and checker. No explicit grants: the role's defaults
-- (authz.ROLE_DEFAULTS) apply until an admin edits it.
INSERT INTO roles (id, tenant_id, name)
SELECT 'role-voice-designer-' || t.id, t.id, 'Voice designer' FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND lower(r.name) = 'voice designer')
ON CONFLICT DO NOTHING;
INSERT INTO roles (id, tenant_id, name)
SELECT 'role-release-approver-' || t.id, t.id, 'Release approver' FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND lower(r.name) = 'release approver')
ON CONFLICT DO NOTHING;

-- One cost statement per tenant, month and environment (billing_jobs builds
-- them on the 1st; rebuilding a draft replaces its lines).
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_tenant_month_env
  ON invoices (tenant_id, invoice_month, environment);

-- A budget alert fires once per rule per month.
ALTER TABLE budget_alert_events ADD COLUMN IF NOT EXISTS budget_month TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_alert_rule_month
  ON budget_alert_events (budget_rule_id, budget_month) WHERE budget_month IS NOT NULL;
