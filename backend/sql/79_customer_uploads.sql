-- A receipt or KYC photo a customer sends is stored in the `customer-uploads`
-- bucket and indexed by a document_files row. The retention sweep
-- (agent_core.retention, kind `customer_upload`) deletes the object and then
-- the row, so each row names its own tenant and expiry.
--
-- tenant_id makes document_files RLS-rooted on the next `rls.py apply`;
-- existing rows are backfilled from their request's customer first, because
-- `enable` refuses a rooted table with NULL-tenant rows. Rows already here
-- were written without a file (the pre-PR-17 phantom writer), so none is
-- stamped: NULL retain_until is never swept.
ALTER TABLE document_files
  ADD COLUMN IF NOT EXISTS tenant_id TEXT REFERENCES tenants(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS retention_class TEXT,
  ADD COLUMN IF NOT EXISTS retain_until timestamptz;

UPDATE document_files f
   SET tenant_id = c.tenant_id
  FROM document_requests r
  JOIN customers_pii c ON c.id = r.customer_id
 WHERE r.id = f.request_id AND f.tenant_id IS NULL;

ALTER TABLE document_files ALTER COLUMN tenant_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_document_files_retention
  ON document_files (tenant_id, retain_until)
  WHERE retain_until IS NOT NULL;
