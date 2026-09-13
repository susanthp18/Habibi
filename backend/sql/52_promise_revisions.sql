-- A promise is one open commitment per account, and it can be renegotiated.
--
-- Nothing held "one open promise per account" although the pay link, the
-- campaign planner and the treatment engine all read as if it were true;
-- and nothing let a borrower who rang to say "salary is late, can I pay on
-- the 20th instead?" be recorded honestly: the PATCH took a new date with no
-- reason and no history, or the desk created a second promise beside the
-- first. Now:
--
--   * `uq_promises_one_open` -- at most one row per account in an open
--     state. A second create is refused with the open one attached, so every
--     client offers "revise the existing promise" instead. Duplicates (none
--     in any known database) are resolved first: the newest stays open, the
--     rest close as cancelled with `cancel_reason = 'superseded_by_migration'`.
--   * `promise_revisions` -- one row per renegotiation: what the commitment
--     was, what it became, why, who asked, on which interaction. The promise
--     keeps its id, its reminders and its pay link (re-derived).
--   * `cancelled` -- a fourth way a commitment ends that is not kept, broken
--     or partial: the borrower withdrew it, a dispute was raised, the account
--     settled otherwise. Carries its reason.
--
-- Also on this pass's migration (one schema change per pass):
--   * `routing_rule_executions (rule_id, evaluated_at)` -- the rules table's
--     LATERAL aggregate per rule had only interaction_id to probe.
--   * `promise_reminders.last_error` -- the sender wrote the error string into
--     provider_delivery_id, so a failed reminder had an "id" and never a SID.
--   * `followups` joins the updated_at trigger list (sql/13); one writer
--     skipped the column.
--   * The two unique indexes sql/41 created under one name and sql/49 under
--     another (same columns) drop the sql/41 names.

-- 1. the promise row: a fourth terminal state and the renegotiation counters
ALTER TABLE promises DROP CONSTRAINT IF EXISTS promises_status_check;
ALTER TABLE promises
  ADD CONSTRAINT promises_status_check
  CHECK (status IN ('upcoming','due_today','kept','broken','partial','cancelled'));
ALTER TABLE promises
  ADD COLUMN IF NOT EXISTS revision_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cancel_reason TEXT,
  ADD COLUMN IF NOT EXISTS cancelled_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancelled_by TEXT;

-- 2. the history
CREATE TABLE IF NOT EXISTS promise_revisions (
  id TEXT PRIMARY KEY,
  promise_id TEXT NOT NULL REFERENCES promises(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  prior_amount numeric(14,2) NOT NULL,
  prior_promised_at timestamptz NOT NULL,
  amount numeric(14,2) NOT NULL,
  promised_at timestamptz NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN (
    'customer_requested_delay','salary_delayed','medical','dispute_raised',
    'partial_payment_agreed','agent_correction','other'
  )),
  note TEXT,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','bot','system')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  actor_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (promise_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_promise_revisions_promise_id ON promise_revisions(promise_id);

-- 3. one open promise per account: resolve any duplicates, then hold the line
WITH ranked AS (
  SELECT id, row_number() OVER (PARTITION BY account_id ORDER BY created_at DESC, id DESC) AS rn
  FROM promises WHERE status IN ('upcoming','due_today')
)
UPDATE promises p
SET status = 'cancelled', cancel_reason = 'superseded_by_migration', cancelled_at = now()
FROM ranked WHERE ranked.id = p.id AND ranked.rn > 1;
CREATE UNIQUE INDEX IF NOT EXISTS uq_promises_one_open
  ON promises (account_id) WHERE status IN ('upcoming','due_today');

-- 4. the crumbs
CREATE INDEX IF NOT EXISTS idx_routing_rule_executions_rule_evaluated
  ON routing_rule_executions (rule_id, evaluated_at DESC);
ALTER TABLE promise_reminders ADD COLUMN IF NOT EXISTS last_error TEXT;
DROP INDEX IF EXISTS uq_emi_installments_slot;
DROP INDEX IF EXISTS uq_promise_installments_slot;
DROP TRIGGER IF EXISTS trg_followups_updated_at ON followups;
CREATE TRIGGER trg_followups_updated_at BEFORE UPDATE ON followups
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
