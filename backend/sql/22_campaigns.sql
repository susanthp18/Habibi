-- ---------------------------------------------------------------------------
-- 22_campaigns.sql — campaign runs, retry cadence state, caller-ID pools.
--
-- Mirrors alembic/versions/20260822_0095_campaign_cadence_numbers.py.
--
-- The treatment engine already answers *who* to call. What had no
-- representation was the batch, the retry ladder, and the number a dial goes
-- out from — so there was nowhere to put a pace, nothing to count attempts
-- against, and one TWILIO_PHONE_NUMBER for every tenant and every purpose.
--
-- References tenants/users/bots (01), customers/accounts (02) and call_attempts
-- (21), so it can only live here or later.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS campaign_runs (
  id                 TEXT PRIMARY KEY,
  tenant_id          TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  bot_id             TEXT REFERENCES bots(id) ON DELETE SET NULL,
  deployment_id      TEXT,
  name               TEXT NOT NULL,
  objective          TEXT NOT NULL,
  cadence            TEXT NOT NULL DEFAULT 'default',
  -- 'list' is an explicit set of borrowers; 'segment' a saved filter; 'engine'
  -- means the treatment engine authorised each member individually and this run
  -- only paces them. A run never decides that somebody who should not be called
  -- should be.
  source             TEXT NOT NULL DEFAULT 'list'
                     CHECK (source IN ('list','segment','engine')),
  selector           jsonb NOT NULL DEFAULT '{}'::jsonb,
  status             TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','running','paused','finished','cancelled')),
  -- Local-time window this run may dial in. Narrower than the statutory window,
  -- never wider: contact_policy still has the final say, so this can only
  -- subtract from what the law already allows.
  window_start_hour  INTEGER NOT NULL DEFAULT 10,
  window_end_hour    INTEGER NOT NULL DEFAULT 18,
  max_concurrent     INTEGER NOT NULL DEFAULT 5,
  max_attempts_total INTEGER,
  targets_total      INTEGER NOT NULL DEFAULT 0,
  targets_done       INTEGER NOT NULL DEFAULT 0,
  created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  started_at         timestamptz,
  paused_at          timestamptz,
  finished_at        timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_campaign_runs_window CHECK (
    window_start_hour >= 0 AND window_end_hour <= 24
    AND window_start_hour < window_end_hour
  ),
  CONSTRAINT ck_campaign_runs_concurrency CHECK (max_concurrent BETWEEN 1 AND 100)
);
CREATE INDEX IF NOT EXISTS idx_campaign_runs_tenant_status
  ON campaign_runs (tenant_id, status);

CREATE TABLE IF NOT EXISTS campaign_targets (
  id              TEXT PRIMARY KEY,
  run_id          TEXT NOT NULL REFERENCES campaign_runs(id) ON DELETE CASCADE,
  customer_id     TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id      TEXT,
  decision_id     TEXT,
  state           TEXT NOT NULL DEFAULT 'pending'
                  CHECK (state IN ('pending','dialing','done','failed','skipped')),
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_attempt_id TEXT,
  outcome         TEXT,
  next_attempt_at timestamptz,
  note            TEXT,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  -- A borrower listed twice in an uploaded file is a data problem, not
  -- permission to call them twice.
  CONSTRAINT ux_campaign_targets_member UNIQUE (run_id, customer_id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_targets_claim
  ON campaign_targets (run_id, next_attempt_at) WHERE state = 'pending';

-- ---------------------------------------------------------------------------
-- The retry ladder. Keyed on the *case*, because that is what persists across
-- dials — an attempt is one dial and is finished when the carrier says so.
--
-- Cadence may retry the same action. Only the treatment engine may change the
-- action; a dialler with its own escalation ladder would have no expected
-- value, no propensity and no audit trail, and would quietly outvote the one
-- that has all three.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS call_cadence_state (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id     TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  objective       TEXT NOT NULL,
  -- Mirrors treatment's case identity so the two loops agree about what "the
  -- same case" means instead of each holding its own opinion.
  case_ref        TEXT NOT NULL DEFAULT '',
  cadence         TEXT NOT NULL DEFAULT 'default',
  attempts        INTEGER NOT NULL DEFAULT 0,
  max_attempts    INTEGER NOT NULL DEFAULT 3,
  next_attempt_at timestamptz,
  last_attempt_id TEXT,
  last_outcome    TEXT,
  state           TEXT NOT NULL DEFAULT 'open'
                  CHECK (state IN ('open','exhausted','stopped','escalated')),
  stopped_reason  TEXT,
  campaign_run_id TEXT,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ux_call_cadence_case UNIQUE (customer_id, objective, case_ref)
);
CREATE INDEX IF NOT EXISTS idx_call_cadence_due
  ON call_cadence_state (next_attempt_at)
  WHERE state = 'open' AND next_attempt_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Caller ID. Three problems, and only the first is obvious: TRAI's 1600 series
-- for BFSI service calls (promotional content not permitted on it); two banks
-- on one deployment cannot share a number; and a number enough handsets have
-- flagged simply stops connecting, with no way to observe it before now.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS number_pools (
  id         TEXT PRIMARY KEY,
  tenant_id  TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'general'
             CHECK (kind IN ('service_1600','promotional','general')),
  enabled    boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ux_number_pools_name UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS pool_numbers (
  id             TEXT PRIMARY KEY,
  pool_id        TEXT NOT NULL REFERENCES number_pools(id) ON DELETE CASCADE,
  e164           TEXT NOT NULL,
  state          TEXT NOT NULL DEFAULT 'active'
                 CHECK (state IN ('active','cooling','retired')),
  last_used_at   timestamptz,
  -- Both maintained by outbound.refresh_pool_health() over a real rolling
  -- seven days of call_attempts. They are not incremented per dial: a counter
  -- that only ever goes up is not a 7-day rate, whatever it is called.
  attempts_7d    INTEGER NOT NULL DEFAULT 0,
  answer_rate_7d numeric(5,4),
  -- Cooling has to be able to end, or one bad week retires a caller ID for the
  -- life of the deployment.
  state_changed_at  timestamptz NOT NULL DEFAULT now(),
  health_checked_at timestamptz,
  note           TEXT,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ux_pool_numbers_e164 UNIQUE (e164)
);
CREATE INDEX IF NOT EXISTS idx_pool_numbers_pick
  ON pool_numbers (pool_id, last_used_at NULLS FIRST) WHERE state = 'active';
