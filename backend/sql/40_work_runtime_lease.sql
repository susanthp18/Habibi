-- `working` becomes a claim with a lease, not a label.
--
-- claim_next selected `status IN ('submitted','working')` and set `working`
-- with nothing else, so a job whose worker died stayed re-selectable by every
-- tick forever, and a job whose handler kept raising was re-run without
-- bound. The same shape bot_turn_jobs already uses: a lock timestamp the
-- claim refreshes and the sweep reads, and an attempt counter with a cap.
ALTER TABLE work_runtime_jobs
  ADD COLUMN IF NOT EXISTS locked_at timestamptz,
  ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
