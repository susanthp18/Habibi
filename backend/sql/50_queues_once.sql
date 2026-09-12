-- Queues that were only tables, and jobs that ran once per process
-- (migration 20260913_0142).
--
-- mcp_tasks had a status and nothing else: no lease, so a worker that died
-- mid-task left it 'running' forever; no attempt count, so a task that
-- failed stayed failed with no retry and no dead letter. It gets the same
-- four columns bot_turn_jobs runs on, and 'dead' joins its vocabulary.
--
-- nightly_runs is the durable "already ran today" for the worker's daily
-- jobs. A module global was the marker before, so two worker replicas ran
-- the TTS sync, the lead revalidation, the gardener and the eval schedule
-- twice a night, and a restarted worker ran them again.

ALTER TABLE mcp_tasks ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mcp_tasks ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;
ALTER TABLE mcp_tasks ADD COLUMN IF NOT EXISTS locked_by TEXT;
ALTER TABLE mcp_tasks ADD COLUMN IF NOT EXISTS run_after TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE mcp_tasks DROP CONSTRAINT IF EXISTS mcp_tasks_status_check;
ALTER TABLE mcp_tasks ADD CONSTRAINT mcp_tasks_status_check
  CHECK (status IN ('queued','running','succeeded','failed','dead'));
CREATE INDEX IF NOT EXISTS idx_mcp_tasks_queue ON mcp_tasks(status, run_after);

CREATE TABLE IF NOT EXISTS nightly_runs (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  job TEXT NOT NULL,
  day DATE NOT NULL,
  ran_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ran_by TEXT,
  PRIMARY KEY (tenant_id, job, day)
);
