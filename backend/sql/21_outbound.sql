-- ---------------------------------------------------------------------------
-- 21_outbound.sql — the outbound attempt, its outcome, and what we promised.
--
-- Mirrors alembic/versions/20260822_0094_outbound_attempts.py. Read that file's
-- docstring for the reasoning; this file exists so a database built from sql/
-- is identical to one built by replaying migrations.
--
-- `call_attempts` is the object every outbound metric is measured on. Before
-- it, an unanswered dial left no trace: `interactions` rows are created from
-- `on_client_connected`, so a ring-out, a busy tone, a dead number and a call
-- the contact gate refused all produced the same evidence, which was none.
-- Answer rate, right-party-contact rate, best-time-to-call and cost per connect
-- were all uncomputable, and `treatment/features.py` was fitting connect_rate
-- to a numerator with no denominator.
--
-- References tenants (01), customers/accounts (02), interactions (04) and
-- treatment_decisions (05), so it can only live here or later.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS call_attempts (
  id                TEXT PRIMARY KEY,
  tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id       TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id        TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  -- Plain TEXT, not FKs: the mission is assembled at dial time and
  -- campaign_runs is a later phase. Adding the constraints later is one ALTER.
  mission_id        TEXT,
  campaign_run_id   TEXT,
  decision_id       TEXT REFERENCES treatment_decisions(id) ON DELETE SET NULL,
  bot_id            TEXT REFERENCES bots(id) ON DELETE SET NULL,
  deployment_id     TEXT,
  objective         TEXT NOT NULL,
  purpose           TEXT NOT NULL DEFAULT 'outreach'
                    CHECK (purpose IN ('outreach','statutory','in_session')),
  attempt_no        INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
  -- The raw number stays on `customers`. A second copy here would be
  -- unredactable borrower PII whose retention nobody has argued about.
  to_phone_hash     TEXT NOT NULL,
  to_phone_last4    TEXT,
  phone_slot        TEXT NOT NULL DEFAULT 'primary',
  from_number       TEXT,
  number_pool       TEXT,
  -- Which rule set authorised this dial. The regulator's question is about a
  -- call, not about a decision, so the stamp lives here as well as on
  -- treatment_decisions.
  policy_version    INTEGER,
  state             TEXT NOT NULL CHECK (state IN (
    'reserved','suppressed','dialing','ringing','answered','live','completed',
    'voicemail_left','voicemail_skipped','no_answer','busy','rejected','failed',
    'invalid_number','canceled','transferred','abandoned'
  )),
  -- Set when contact_policy refused. A refused attempt is still a row: that is
  -- what turns "our denial rate is 14%" from a log-grep into a query.
  suppressed_reason TEXT,
  reserved_at       timestamptz NOT NULL DEFAULT now(),
  placed_at         timestamptz,
  answered_at       timestamptz,
  ended_at          timestamptz,
  ring_sec          INTEGER,
  talk_sec          INTEGER,
  provider          TEXT NOT NULL DEFAULT 'twilio',
  provider_call_id  TEXT,
  provider_status   TEXT,
  provider_error    TEXT,
  price_inr         numeric(10,4),
  answered_by       TEXT CHECK (answered_by IS NULL OR answered_by IN
                      ('human','machine','ivr','fax','unknown')),
  right_party       boolean,
  interaction_id    TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  -- The Closer's queue marker: NULL means this attempt still owes an outcome.
  closed_at         timestamptz,
  context           jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_attempts_customer_reserved
  ON call_attempts (customer_id, reserved_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_attempts_decision ON call_attempts (decision_id);
CREATE INDEX IF NOT EXISTS idx_call_attempts_tenant_reserved
  ON call_attempts (tenant_id, reserved_at DESC);
-- In-flight lookup for the concurrency gate. Partial, so the index stays the
-- size of the live fleet rather than the size of the log.
CREATE INDEX IF NOT EXISTS idx_call_attempts_in_flight
  ON call_attempts (tenant_id, reserved_at)
  WHERE state IN ('reserved','dialing','ringing','answered','live');
CREATE INDEX IF NOT EXISTS idx_call_attempts_unclosed
  ON call_attempts (ended_at)
  WHERE closed_at IS NULL AND state <> 'reserved';
-- Twilio retries its status callbacks; two rows for one call would double-count
-- every reach metric built on this table.
CREATE UNIQUE INDEX IF NOT EXISTS ux_call_attempts_provider_call
  ON call_attempts (provider, provider_call_id)
  WHERE provider_call_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- The outcome, on two independent axes.
--
-- `interactions.disposition` holds one of four values derived from three
-- booleans, and it conflates "did the phone connect" with "did the conversation
-- work". Splitting them is what makes `no_answer` retryable and `refused` not.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS call_outcomes (
  id                   TEXT PRIMARY KEY,
  attempt_id           TEXT NOT NULL REFERENCES call_attempts(id) ON DELETE CASCADE,
  tenant_id            TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id          TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  interaction_id       TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  mission_id           TEXT,
  decision_id          TEXT,
  objective            TEXT,
  connection           TEXT NOT NULL CHECK (connection IN (
    'no_answer','busy','rejected','failed','invalid_number','voicemail',
    'wrong_party','ivr_only','connected','suppressed'
  )),
  business             TEXT CHECK (business IS NULL OR business IN (
    'ptp_captured','ptp_recommitted','paid_in_call','part_payment_agreed',
    'plan_agreed','dispute_raised','hardship_declared','refused',
    'callback_requested','wrong_number','deceased','opt_out_requested',
    'escalated','no_resolution','abandoned_by_customer'
  )),
  objective_met        boolean NOT NULL DEFAULT false,
  -- A dictionary, not free text. The value is in segmenting the book by it, and
  -- `forgot` is the label that tells the engine it spent a voice call on
  -- somebody an SMS would have cured.
  nonpayment_reason    TEXT CHECK (nonpayment_reason IS NULL OR nonpayment_reason IN (
    'salary_timing','income_loss','medical','mandate_broken','disputes_amount',
    'competing_obligation','forgot','unwilling','not_stated'
  )),
  commitment           jsonb,
  objections           jsonb NOT NULL DEFAULT '[]'::jsonb,
  unanswered_questions jsonb NOT NULL DEFAULT '[]'::jsonb,
  sentiment_start      numeric(5,3),
  sentiment_end        numeric(5,3),
  escalation           TEXT NOT NULL DEFAULT 'none'
                       CHECK (escalation IN ('none','requested','auto','transferred')),
  compliance_flags     jsonb NOT NULL DEFAULT '[]'::jsonb,
  next_action_hint     TEXT,
  summary              TEXT NOT NULL DEFAULT '',
  -- 'template' when the LLM was unavailable, refused, or wrote a number it was
  -- not given. A reader can then tell a written summary from a generated one
  -- rather than trusting all of them equally.
  summary_source       TEXT NOT NULL DEFAULT 'template'
                       CHECK (summary_source IN ('template','llm')),
  summary_model        TEXT,
  actions_applied      jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at           timestamptz NOT NULL DEFAULT now(),
  -- One outcome per attempt; this is also what makes the join safe without a
  -- pointer column on call_attempts that could disagree with it.
  CONSTRAINT ux_call_outcomes_attempt UNIQUE (attempt_id)
);
CREATE INDEX IF NOT EXISTS idx_call_outcomes_customer ON call_outcomes (customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_call_outcomes_business ON call_outcomes (business);
CREATE INDEX IF NOT EXISTS idx_call_outcomes_reason ON call_outcomes (nonpayment_reason);

-- ---------------------------------------------------------------------------
-- Things *we* promised. "I'll call you Tuesday at six" was previously spoken
-- and forgotten; an agent that keeps its promises is the whole trust
-- proposition of an automated collections line.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_obligations (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id    TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  attempt_id     TEXT REFERENCES call_attempts(id) ON DELETE SET NULL,
  kind           TEXT NOT NULL CHECK (kind IN
                   ('callback','document','escalation','correction','waiver','written_confirm')),
  due_at         timestamptz NOT NULL,
  detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- What the agent actually said. A paraphrase is not evidence, and this column
  -- is the evidence for "did we keep our word".
  verbatim       TEXT,
  state          TEXT NOT NULL DEFAULT 'open'
                 CHECK (state IN ('open','honoured','missed','cancelled')),
  honoured_at    timestamptz,
  honoured_ref   TEXT,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_obligations_due
  ON agent_obligations (due_at) WHERE state = 'open';
CREATE INDEX IF NOT EXISTS idx_agent_obligations_customer ON agent_obligations (customer_id);
