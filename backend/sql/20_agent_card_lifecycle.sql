-- Agent card lifecycle: archive instead of delete.
--
-- bots.id is referenced by interactions, eval_reports, activity_events and
-- a2a_tasks. Deleting a bot that ever handled a call would CASCADE its
-- deployments and NULL its audit rows, so a retired agent has to stay a row.
ALTER TABLE bots
  ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_bots_archived_at ON bots (archived_at);
