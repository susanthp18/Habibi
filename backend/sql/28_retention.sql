-- W8b · retention: every record knows when it dies, and why.
--
-- §14.2 of engines-production-design.md. Today `treatment_decisions` has no
-- retention and no archive path: it grows forever, and "until purpose served"
-- -- which is the statutory standard, not a schedule -- is answered nowhere.
--
-- Two properties from §14.2 are load-bearing and both are here:
--
--   `retain_until` is a PER-RECORD column computed AT WRITE from a documented
--   rule per record kind, with the Rule 8(3) floor applied as max(). Not a
--   query predicate evaluated at purge time: a rule that changes must not
--   silently re-date a million rows that were written under the old one.
--
--   The rule that computes it is a ROW WITH A CITATION. Asked why a record was
--   destroyed on a particular day, the answer is an instrument, not a constant
--   in a Python file.
--
-- What is NOT here, stated so the gap is a decision rather than a silence:
-- the encrypted Parquet archive and the monthly `retention_class`
-- sub-partition. The sub-partition is what makes expiry a DETACH rather than
-- an UPDATE, and it needs the expand/contract cutover of §15.1 item 4 that
-- `treatment/partitions.py` currently only scaffolds. At this book size an
-- UPDATE is correct and a DETACH is merely faster.

-- ---------------------------------------------------------------------------
-- The rules
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS retention_rules (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  -- What kind of record this governs. One rule per kind per tenant in force.
  record_kind TEXT NOT NULL,
  retention_class TEXT NOT NULL CHECK (retention_class IN (
    'identified', 'pseudonymous', 'recording', 'processing_log', 'evaluation'
  )),
  -- Which timestamp starts the clock. "Loan closure + N", "last contact + N"
  -- and "complaint close + N" are different anchors, and banding them into one
  -- created_at rule is how a record outlives its purpose or dies before it.
  anchor TEXT NOT NULL,
  retain_days INTEGER NOT NULL CHECK (retain_days > 0),
  -- The statutory minimum, applied as max(retain_days, floor_days). A tenant
  -- may keep a record longer than the floor; it may never keep it less.
  floor_days INTEGER NOT NULL CHECK (floor_days >= 0),
  citation TEXT NOT NULL CHECK (length(btrim(citation)) > 0),
  effective tstzrange NOT NULL DEFAULT tstzrange(now(), NULL),
  changed_by TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
  created_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ck_retention_rules_nonempty CHECK (NOT isempty(effective)),
  CONSTRAINT ck_retention_rules_maker_checker CHECK (changed_by <> approved_by),
  CONSTRAINT ex_retention_rules_current EXCLUDE USING gist (
    tenant_id WITH =, record_kind WITH =, effective WITH &&
  )
);

-- ---------------------------------------------------------------------------
-- The subject register
-- ---------------------------------------------------------------------------

-- One pseudonym per subject per tenant, destroyable on its own.
--
-- §14.2: "The keys are per subject, which is what makes crypto-shredding mean
-- anything -- a per-tenant salt cannot be destroyed for one borrower, and
-- every row of the same borrower sharing a hash, combined with exact
-- outstanding, exact DPD, exact EV and geography-derived features, is
-- trivially re-identifiable by anyone holding both."
--
-- What this table does today: it is the register and the destruction record.
-- `subject_rights.fulfil_erasure` marks a subject's pseudonym destroyed, and
-- that is the evidence a DPDP erasure was carried out beyond cancelling plans
-- -- which is all it did before, and its own docstring said so.
--
-- What it does NOT do yet: hold key material for an encrypted archive. There
-- is no archive; a key column with nothing encrypted under it would be
-- theatre. `pseudonym` is what the archive will carry in place of
-- `customer_id`, and destroying the row is what will make those bytes
-- unreadable. See the class table in §14.2.
CREATE TABLE IF NOT EXISTS subject_keys (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  subject_kind TEXT NOT NULL DEFAULT 'customer',
  subject_id TEXT NOT NULL,
  pseudonym TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  destroyed_at timestamptz,
  destroyed_by TEXT,
  destroy_reason TEXT,

  CONSTRAINT uq_subject_keys_subject UNIQUE (tenant_id, subject_kind, subject_id),
  CONSTRAINT uq_subject_keys_pseudonym UNIQUE (tenant_id, pseudonym),
  CONSTRAINT ck_subject_keys_destroyed CHECK (
    destroyed_at IS NULL OR destroy_reason IS NOT NULL
  )
);

-- ---------------------------------------------------------------------------
-- Recording holds
-- ---------------------------------------------------------------------------

-- Call audio lives on the bank's NFS and is purged BY US against this table.
-- §14.2: max(6 months, DPDP Rule 8(3) 1 year, open hold + 90 days) -- the
-- recovery-conduct six-month rule is a FLOOR, not a ceiling, and an open hold
-- outranks both.
CREATE TABLE IF NOT EXISTS recording_holds (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  customer_id TEXT REFERENCES customers_pii(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE CASCADE,
  reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
  basis TEXT,
  opened_at timestamptz NOT NULL DEFAULT now(),
  opened_by TEXT,
  released_at timestamptz,
  released_by TEXT,

  -- A hold on nothing is not a hold.
  CONSTRAINT ck_recording_holds_target CHECK (
    customer_id IS NOT NULL OR interaction_id IS NOT NULL
  )
);
CREATE INDEX IF NOT EXISTS idx_recording_holds_open
  ON recording_holds (tenant_id, customer_id, interaction_id)
  WHERE released_at IS NULL;

-- ---------------------------------------------------------------------------
-- What the sweep did
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS retention_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  record_kind TEXT NOT NULL,
  ran_at timestamptz NOT NULL DEFAULT now(),
  scanned INTEGER NOT NULL DEFAULT 0,
  redacted INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  held INTEGER NOT NULL DEFAULT 0,
  rule_id TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_retention_runs_recent
  ON retention_runs (tenant_id, ran_at DESC);

-- ---------------------------------------------------------------------------
-- The per-record columns
-- ---------------------------------------------------------------------------

-- Stamped at write, never recomputed at purge time. `retention_class` moves
-- exactly once per row, identified -> pseudonymous, when the free text is
-- redacted in place; the second clock then runs from that moment.
ALTER TABLE treatment_decisions
  ADD COLUMN IF NOT EXISTS retention_class TEXT,
  ADD COLUMN IF NOT EXISTS retain_until timestamptz;
ALTER TABLE contact_events
  ADD COLUMN IF NOT EXISTS retention_class TEXT,
  ADD COLUMN IF NOT EXISTS retain_until timestamptz;
ALTER TABLE interactions
  ADD COLUMN IF NOT EXISTS retention_class TEXT,
  ADD COLUMN IF NOT EXISTS retain_until timestamptz;
ALTER TABLE offer_decisions
  ADD COLUMN IF NOT EXISTS retention_class TEXT,
  ADD COLUMN IF NOT EXISTS retain_until timestamptz;

-- The sweep's only predicate. Partial, so it sheds every row that is not yet
-- due instead of carrying the whole table -- the failure mode §14.2 names for
-- the four indexes that already grow without bound.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_retention
  ON treatment_decisions (tenant_id, retain_until)
  WHERE retain_until IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contact_events_retention
  ON contact_events (tenant_id, retain_until)
  WHERE retain_until IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_interactions_retention
  ON interactions (tenant_id, retain_until)
  WHERE retain_until IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_offer_decisions_retention
  ON offer_decisions (tenant_id, retain_until)
  WHERE retain_until IS NOT NULL;
