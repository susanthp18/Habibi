-- Status columns state their vocabulary (migration 20260912_0137).
--
-- Four status columns had no CHECK while a partial index and every sweep
-- predicate depended on the literal 'active'; a typo status was an account
-- the collector could not see. Each vocabulary has one owner:
--   accounts.status      lms_account_status.normalised (sql/24) -- what the
--                        bank feed maps into, fail-closed
--   payment_plans.status the plan writer (db.create_payment_plan) -- only
--                        ever 'active' today; the wire's on_track/slipped is
--                        derived from the promises, not stored
--   invoices.status      schemas.BillingInvoiceStatus
--   export_jobs.status   schemas.ExportStatus / followups_db._EXPORT_STATUSES
-- tests/test_status_vocabularies.py compares the live constraints to those.
--
-- Two adjacent fossils go with it: ledger_entries.balance, written by none
-- of the five ledger writers and rendered as an empty "Balance" column on
-- the Customer 360; and supervisor_actions ON DELETE CASCADE from users --
-- deleting a supervisor deleted the audit of every barge and whisper they
-- ever made. RESTRICT: a supervisor with history is deactivated, not deleted.

ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_status_check;
ALTER TABLE accounts ADD CONSTRAINT accounts_status_check
  CHECK (status IN ('active','closed','charged_off','sold','frozen','unknown'));

ALTER TABLE payment_plans DROP CONSTRAINT IF EXISTS payment_plans_status_check;
ALTER TABLE payment_plans ADD CONSTRAINT payment_plans_status_check
  CHECK (status IN ('active','completed','cancelled'));

ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_status_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_status_check
  CHECK (status IN ('draft','pending','paid'));

-- The seed wrote 'completed'; the code has mapped it to 'ready' on every read.
UPDATE export_jobs SET status = 'ready' WHERE status = 'completed';
ALTER TABLE export_jobs DROP CONSTRAINT IF EXISTS export_jobs_status_check;
ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_status_check
  CHECK (status IN ('queued','ready','failed'));

ALTER TABLE ledger_entries DROP COLUMN IF EXISTS balance;

ALTER TABLE supervisor_actions
  DROP CONSTRAINT IF EXISTS supervisor_actions_supervisor_user_id_fkey;
ALTER TABLE supervisor_actions
  ADD CONSTRAINT supervisor_actions_supervisor_user_id_fkey
  FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE RESTRICT;
