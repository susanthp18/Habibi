-- Two tables that carried no tenant of their own.
--
-- `faq_pairs` reached its tenant only through `linked_document_id`, and
-- `ledger_entries` only through `accounts` -> `customers`. Both were readable
-- across tenants by any query that did not walk that join -- `kb_retrieve`'s
-- FAQ arm did not, so a borrower at one bank could be answered from another
-- bank's FAQ. And a row-level policy on the column is a predicate; one on a
-- two-hop EXISTS is a plan.
--
-- Nullable on purpose, with a BEFORE INSERT default that resolves the tenant
-- from the row's own foreign key, so no writer has to change today. A row that
-- somehow arrives with neither is left NULL -- which under row-level security
-- is a row nobody can read. Fail closed, and visible as a count.
--
-- Backfill is one UPDATE per table over 119 and 334 rows measured on
-- `collections` on 2026-09-11; every row resolves (all 119 FAQ pairs link a
-- document, all 334 ledger rows have an account with a customer).

-- ---------------------------------------------------------------------------
-- faq_pairs
-- ---------------------------------------------------------------------------

ALTER TABLE faq_pairs
  ADD COLUMN IF NOT EXISTS tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE;

UPDATE faq_pairs f
   SET tenant_id = d.tenant_id
  FROM kb_documents d
 WHERE d.id = f.linked_document_id
   AND f.tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_faq_pairs_tenant ON faq_pairs (tenant_id);

CREATE OR REPLACE FUNCTION faq_pairs_default_tenant()
RETURNS trigger AS $$
BEGIN
  IF NEW.tenant_id IS NULL AND NEW.linked_document_id IS NOT NULL THEN
    SELECT tenant_id INTO NEW.tenant_id FROM kb_documents WHERE id = NEW.linked_document_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_faq_pairs_default_tenant ON faq_pairs;
CREATE TRIGGER trg_faq_pairs_default_tenant
  BEFORE INSERT ON faq_pairs
  FOR EACH ROW EXECUTE FUNCTION faq_pairs_default_tenant();

-- ---------------------------------------------------------------------------
-- ledger_entries
-- ---------------------------------------------------------------------------

ALTER TABLE ledger_entries
  ADD COLUMN IF NOT EXISTS tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE;

UPDATE ledger_entries l
   SET tenant_id = c.tenant_id
  FROM accounts a
  JOIN customers c ON c.id = a.customer_id
 WHERE a.id = l.account_id
   AND l.tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_ledger_entries_tenant ON ledger_entries (tenant_id, posted_at DESC);

CREATE OR REPLACE FUNCTION ledger_entries_default_tenant()
RETURNS trigger AS $$
BEGIN
  IF NEW.tenant_id IS NULL AND NEW.account_id IS NOT NULL THEN
    SELECT c.tenant_id INTO NEW.tenant_id
      FROM accounts a JOIN customers c ON c.id = a.customer_id
     WHERE a.id = NEW.account_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ledger_entries_default_tenant ON ledger_entries;
CREATE TRIGGER trg_ledger_entries_default_tenant
  BEFORE INSERT ON ledger_entries
  FOR EACH ROW EXECUTE FUNCTION ledger_entries_default_tenant();
