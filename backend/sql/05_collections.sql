CREATE TABLE IF NOT EXISTS payment_plans (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'active',
  total_amount numeric(14,2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_payment_plans_customer_id ON payment_plans(customer_id);

CREATE TABLE IF NOT EXISTS promises (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  owner_kind TEXT NOT NULL CHECK (owner_kind IN ('human','bot')),
  owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  owner_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  plan_id TEXT REFERENCES payment_plans(id) ON DELETE SET NULL,
  amount numeric(14,2) NOT NULL,
  promised_at timestamptz NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('upcoming','due_today','kept','broken','partial')),
  reminder_status TEXT NOT NULL CHECK (reminder_status IN ('off','queued','scheduled','sent','acknowledged','failed')),
  paid_amount numeric(14,2) NOT NULL DEFAULT 0,
  channel TEXT CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (owner_kind='human' AND owner_user_id IS NOT NULL AND owner_bot_id IS NULL)
    OR (owner_kind='bot' AND owner_bot_id IS NOT NULL AND owner_user_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_promises_customer_id ON promises(customer_id);
CREATE INDEX IF NOT EXISTS idx_promises_account_id ON promises(account_id);
CREATE INDEX IF NOT EXISTS idx_promises_interaction_id ON promises(interaction_id);
CREATE INDEX IF NOT EXISTS idx_promises_status ON promises(status);

CREATE TABLE IF NOT EXISTS promise_reminders (
  id TEXT PRIMARY KEY,
  promise_id TEXT NOT NULL REFERENCES promises(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  kind TEXT NOT NULL DEFAULT 'due' CHECK (kind IN ('confirm','due')),
  scheduled_at timestamptz,
  sent_at timestamptz,
  status TEXT NOT NULL CHECK (status IN ('off','queued','scheduled','sent','acknowledged','failed')),
  provider_delivery_id TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_promise_reminders_promise_id ON promise_reminders(promise_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_promise_reminders_due
  ON promise_reminders (promise_id)
  WHERE kind = 'due';
CREATE INDEX IF NOT EXISTS idx_promise_reminders_due_drain
  ON promise_reminders (status, scheduled_at)
  WHERE kind IN ('confirm','due') AND status IN ('queued','scheduled');

-- Money object for a PTP (or same-day pay-now, which is still a PTP).
-- The promise is the commitment; this row is the pay-link + settlement.
CREATE TABLE IF NOT EXISTS payment_intents (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  promise_id TEXT REFERENCES promises(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  amount numeric(14,2) NOT NULL,
  currency TEXT NOT NULL DEFAULT 'INR',
  public_token TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('created','sent','opened','paid','expired','failed','cancelled')),
  provider TEXT NOT NULL DEFAULT 'hosted' CHECK (provider IN ('hosted','razorpay')),
  provider_ref TEXT,
  pay_url TEXT,
  expires_at timestamptz,
  paid_at timestamptz,
  ledger_entry_id TEXT REFERENCES ledger_entries(id) ON DELETE SET NULL,
  confirm_channel TEXT CHECK (confirm_channel IS NULL OR confirm_channel IN ('whatsapp','sms')),
  suppression_reason TEXT,
  phone_last4 TEXT,
  payment_event_id TEXT REFERENCES payment_events(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_intents_public_token
  ON payment_intents (public_token);
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_intents_open_promise
  ON payment_intents (promise_id)
  WHERE promise_id IS NOT NULL AND status IN ('created','sent','opened');
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_intents_open_event
  ON payment_intents (payment_event_id)
  WHERE payment_event_id IS NOT NULL AND status IN ('created','sent','opened');
CREATE INDEX IF NOT EXISTS idx_payment_intents_tenant_id ON payment_intents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_customer_id ON payment_intents(customer_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_promise_id ON payment_intents(promise_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_payment_event_id ON payment_intents(payment_event_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_status ON payment_intents(status);

CREATE TABLE IF NOT EXISTS promise_installments (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES payment_plans(id) ON DELETE CASCADE,
  installment_index INTEGER NOT NULL,
  due_date timestamptz NOT NULL,
  amount numeric(14,2) NOT NULL,
  paid_status TEXT NOT NULL CHECK (paid_status IN ('upcoming','due_today','kept','broken','partial')),
  paid_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_promise_installments_plan_id ON promise_installments(plan_id);

CREATE TABLE IF NOT EXISTS disputes (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  type TEXT NOT NULL CHECK (type IN ('paid_already','wrong_amount','not_my_account','fee_waiver','duplicate_charge','fraud')),
  disputed_amount numeric(14,2),
  source TEXT,
  status TEXT NOT NULL CHECK (status IN ('new','under_review','awaiting_customer','resolved','rejected')),
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  resolution_code TEXT,
  resolution_notes TEXT,
  sla_due_at timestamptz,
  transcript_snippet TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_disputes_customer_id ON disputes(customer_id);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status);

CREATE TABLE IF NOT EXISTS dispute_evidence (
  id TEXT PRIMARY KEY,
  dispute_id TEXT NOT NULL REFERENCES disputes(id) ON DELETE CASCADE,
  storage_ref TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes bigint,
  hash TEXT,
  uploaded_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dispute_evidence_dispute_id ON dispute_evidence(dispute_id);

CREATE TABLE IF NOT EXISTS document_templates (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  doc_type TEXT NOT NULL,
  preview_lines jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_templates_tenant_id ON document_templates(tenant_id);

CREATE TABLE IF NOT EXISTS document_requests (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  template_id TEXT REFERENCES document_templates(id),
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  doc_type TEXT NOT NULL,
  period TEXT,
  requested_via TEXT CHECK (requested_via IS NULL OR requested_via IN ('bot_voice','bot_chat','agent')),
  delivery_channel TEXT NOT NULL CHECK (delivery_channel IN ('whatsapp','email','sms')),
  delivery_target TEXT,
  status TEXT NOT NULL CHECK (status IN ('requested','generating','sent','failed')),
  failed_reason TEXT,
  size_kb INTEGER,
  generated_at timestamptz,
  sent_at timestamptz,
  attempts INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  sla_due_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_requests_customer_id ON document_requests(customer_id);
CREATE INDEX IF NOT EXISTS idx_document_requests_status ON document_requests(status);

CREATE TABLE IF NOT EXISTS document_files (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES document_requests(id) ON DELETE CASCADE,
  storage_ref TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes bigint,
  hash TEXT,
  generated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_files_request_id ON document_files(request_id);

CREATE TABLE IF NOT EXISTS document_delivery_attempts (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES document_requests(id) ON DELETE CASCADE,
  file_id TEXT REFERENCES document_files(id) ON DELETE SET NULL,
  channel TEXT NOT NULL CHECK (channel IN ('whatsapp','email','sms')),
  target TEXT,
  provider TEXT,
  provider_message_id TEXT,
  attempt_number INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','sent','delivered','failed','bounced')),
  error TEXT,
  sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_delivery_attempts_request_id ON document_delivery_attempts(request_id);

CREATE TABLE IF NOT EXISTS callbacks (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  scheduled_at timestamptz NOT NULL,
  window_mins INTEGER NOT NULL DEFAULT 30,
  dnd_active boolean NOT NULL DEFAULT false,
  status TEXT NOT NULL CHECK (status IN ('scheduled','reminded','in_progress','completed','missed','rescheduled','cancelled')),
  disposition TEXT,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  transcript_snippet TEXT,
  outcome_notes TEXT,
  sla_due_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_callbacks_customer_id ON callbacks(customer_id);
CREATE INDEX IF NOT EXISTS idx_callbacks_scheduled_at ON callbacks(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_callbacks_status ON callbacks(status);

CREATE TABLE IF NOT EXISTS callback_reminders (
  id TEXT PRIMARY KEY,
  callback_id TEXT NOT NULL REFERENCES callbacks(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  scheduled_at timestamptz,
  sent_at timestamptz,
  status TEXT NOT NULL CHECK (status IN ('off','queued','scheduled','sent','acknowledged','failed')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_callback_reminders_callback_id ON callback_reminders(callback_id);

CREATE TABLE IF NOT EXISTS followups (
  id TEXT PRIMARY KEY,
  promise_id TEXT REFERENCES promises(id) ON DELETE CASCADE,
  lead_id TEXT,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('open','in_progress','snoozed','done','cancelled')),
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  due_at timestamptz NOT NULL,
  note TEXT,
  channel TEXT NOT NULL DEFAULT 'voice' CHECK (channel IN ('voice','whatsapp','email','sms')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((promise_id IS NOT NULL)::int + (lead_id IS NOT NULL)::int = 1)
);
CREATE INDEX IF NOT EXISTS idx_followups_customer_id ON followups(customer_id);
CREATE INDEX IF NOT EXISTS idx_followups_promise_id ON followups(promise_id);


-- P3 next-best-treatment ------------------------------------------------------
-- A hold is the veto that had no home. Hardship, an open dispute, a regulatory
-- complaint, bereavement and a matter with legal are all reasons to stop
-- dunning someone; all five lived as prose in the policy corpus or as a routing
-- rule that only fired if a human was already on the call. As a row, a bot at
-- 02:00 is bound by it exactly as a supervisor is.
CREATE TABLE IF NOT EXISTS treatment_holds (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  -- NULL means the whole customer. Hardship is a person; a dispute is usually
  -- one account.
  account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('hardship','dispute','complaint','bereavement','legal')),
  reason TEXT,
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','bot','system','regulator')),
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  placed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  specialist_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  sla_due_at timestamptz,
  starts_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  released_at timestamptz,
  released_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  released_reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_treatment_holds_tenant_id ON treatment_holds(tenant_id);
CREATE INDEX IF NOT EXISTS idx_treatment_holds_customer_id ON treatment_holds(customer_id);
-- The engine's hot read: every active hold for one customer.
CREATE INDEX IF NOT EXISTS idx_treatment_holds_active
  ON treatment_holds (customer_id, kind)
  WHERE released_at IS NULL;
-- COALESCE because a NULL account_id is "the whole customer", and Postgres
-- would otherwise treat two customer-level hardship holds as distinct rows.
CREATE UNIQUE INDEX IF NOT EXISTS uq_treatment_holds_active
  ON treatment_holds (customer_id, COALESCE(account_id, ''), kind)
  WHERE released_at IS NULL;

-- Append-only. Every invocation is written, including the ones that decided to
-- do nothing and including shadow runs that were never enacted: a log holding
-- only the actions we took has no negative class in it, so it can neither train
-- a model nor answer "why did the engine go quiet on Tuesday?".
CREATE TABLE IF NOT EXISTS treatment_decisions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN (
    'bounce','broken_ptp','pre_due','dpd_tick','inbound','manual','no_contact','wrap_up'
  )),
  trigger_ref TEXT,
  -- 'simulated' lets a synthetic corpus live in the real table and be excluded
  -- everywhere by one predicate, which is the convention
  -- scripts/simulate_offer_decisions.py already set for offer_decisions.
  mode TEXT NOT NULL CHECK (mode IN ('off','shadow','live','simulated')),
  variant TEXT,
  recommender TEXT NOT NULL,
  recommender_version TEXT NOT NULL,
  feature_schema_version TEXT NOT NULL,
  features jsonb NOT NULL DEFAULT '{}'::jsonb,
  candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
  excluded jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- represent_mandate, emi_date_change and self_service_plan all have
  -- channel=None, so none of them widens what the contact-frequency cap
  -- governs. Each carries its own veto in treatment/policy.py instead, which
  -- is the obligation that comes with the exemption.
  chosen_action TEXT CHECK (chosen_action IS NULL OR chosen_action IN (
    'wait','sms','whatsapp','voice_bot','human_call','field_visit','legal_notice',
    'represent_mandate','emi_date_change','self_service_plan'
  )),
  chosen_channel TEXT CHECK (chosen_channel IS NULL OR chosen_channel IN (
    'voice','whatsapp','sms','email','chat','field'
  )),
  scheduled_at timestamptz,
  expected_value numeric(14,2),
  -- π(a|x): the probability the logging policy assigned to the action it took.
  -- Strictly positive — an action assigned zero probability is one the policy
  -- could not have taken, and every off-policy estimator divides by this.
  -- Without it a deterministic argmax gives every action a propensity of 1.0
  -- and the log cannot answer what a different policy would have recovered.
  propensity double precision CONSTRAINT ck_treatment_decisions_propensity
    CHECK (propensity IS NULL OR (propensity > 0 AND propensity <= 1)),
  -- Which rule set approved this. A regulator asking "why did you dial at
  -- 19:15 last March?" needs "under the rule set in force then", and that
  -- turns a rule change into a backfill rather than a fresh start.
  policy_version INTEGER,
  explore_kind TEXT CONSTRAINT ck_treatment_decisions_explore_kind
    CHECK (explore_kind IS NULL OR explore_kind IN ('greedy','ranked','control_arm')),
  suppression_reason TEXT,
  rationale TEXT,
  latency_ms INTEGER,
  enacted boolean NOT NULL DEFAULT false,
  enacted_at timestamptz,
  enacted_ref TEXT,
  -- 'unresolved' is the counterfactual's negative class: we deliberately
  -- withheld treatment and the borrower did not pay within the observation
  -- window. Distinct from 'no_answer' because nobody was asked, so nobody
  -- failed to answer -- and without it a control arm contains only positives,
  -- every cure rate it measures is 1.0, and the estimated treatment effect is
  -- a finding about the labeller rather than about collections.
  outcome TEXT CHECK (outcome IS NULL OR outcome IN (
    'reached','no_answer','paid','ptp','refused','undeliverable','cancelled',
    'superseded','unresolved'
  )),
  outcome_at timestamptz,
  -- When the attribution loop last looked at this row and could not yet say.
  --
  -- Not bookkeeping: it is what stops head-of-line blocking. Ordering the
  -- attribution queue by created_at alone meant a row that can never be
  -- labelled -- an unenacted shadow decision outside a withholding arm -- sat
  -- at the front of every pass forever. Twenty-five of those (one batch) and
  -- the loop stops labelling anything at all, silently, during exactly the
  -- shadow fortnight the rollout prescribes.
  outcome_checked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_tenant_id ON treatment_decisions(tenant_id);
-- The attribution loop's queue: never-examined rows first, then least-recently
-- examined. Partial, because only rows still awaiting an outcome are ordered
-- by it and on a live book those are a small and shrinking slice.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_attribution
  ON treatment_decisions (outcome_checked_at NULLS FIRST, created_at)
  WHERE outcome IS NULL;
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_customer
  ON treatment_decisions (customer_id, created_at);
-- The shadow scoreboard groups by mode over a window.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_mode_created
  ON treatment_decisions (mode, created_at);
-- The executor's claim query: due, not yet enacted.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_due
  ON treatment_decisions (scheduled_at)
  WHERE enacted IS FALSE AND chosen_action IS NOT NULL AND chosen_action <> 'wait';
-- The book sweep's "have we already decided this account today?" lookup.
-- trigger_ref is the local ISO date, so the case key is
-- (customer, 'dpd_tick', '2026-08-21').
--
-- Deliberately NOT unique. A day's sweep is one decision per account, but the
-- case it opens is re-decided by the ladder every time an attempt fails to
-- resolve it — that is what makes it a ladder rather than a single suggestion.
-- A unique index forbids the second rung. Concurrency belongs to the sweep's
-- SELECT ... FOR UPDATE SKIP LOCKED on the account row, not to this index.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_sweep
  ON treatment_decisions (customer_id, trigger_ref)
  WHERE trigger_kind = 'dpd_tick' AND trigger_ref IS NOT NULL;
-- Off-policy evaluation reads the corpus by mode and arm. Without this it is a
-- sequential scan over every decision ever made.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_ope
  ON treatment_decisions (mode, variant, created_at)
  WHERE propensity IS NOT NULL;


-- Mandates -------------------------------------------------------------------
-- In Indian retail lending the highest-yield early-bucket action is frequently
-- not a contact at all: it is re-presenting the mandate against the borrower's
-- salary credit. It costs approximately nothing, annoys nobody, and is
-- invisible to the contact-frequency cap.
--
-- payment_events.reason has carried the four diagnostic return codes since the
-- schema was written, and nothing ever branched on them, because there was
-- nowhere to record a presentation. These two tables are that place.
CREATE TABLE IF NOT EXISTS mandates (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  rail TEXT NOT NULL CHECK (rail IN ('nach','enach','upi_autopay','ecs')),
  -- The Unique Mandate Reference Number. Null while registration is pending:
  -- the rail assigns it, we do not.
  umrn TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (
    status IN ('pending','active','suspended','cancelled','expired')
  ),
  max_amount numeric(14,2),
  -- The presentment calendar, in one column. Everything else about when to
  -- present is derived from the salary credit rather than from a calendar
  -- rule, which is the entire point of the action.
  debit_day smallint CHECK (debit_day IS NULL OR debit_day BETWEEN 1 AND 31),
  first_collection_on date,
  final_collection_on date,
  bank_name TEXT,
  account_last4 TEXT,
  registered_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- Partial: a mandate awaiting registration has no UMRN, and two of those are
-- two different mandates rather than a collision.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mandates_umrn
  ON mandates (tenant_id, umrn) WHERE umrn IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mandates_tenant_id ON mandates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mandates_customer_id ON mandates(customer_id);
-- The engine's hot read: is there a presentable mandate on this account?
CREATE INDEX IF NOT EXISTS idx_mandates_account_active
  ON mandates (account_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS mandate_presentations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  mandate_id TEXT NOT NULL REFERENCES mandates(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  emi_installment_id TEXT REFERENCES emi_installments(id) ON DELETE SET NULL,
  amount numeric(14,2) NOT NULL,
  -- The cycle this settles, not the day we asked for it. Two presentations of
  -- the same cycle are a retry and count against the presentation limit; two
  -- of different cycles are ordinary collection and do not.
  presented_for date NOT NULL,
  attempt_no smallint NOT NULL DEFAULT 1,
  scheduled_at timestamptz,
  presented_at timestamptz,
  settled_at timestamptz,
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK (
    status IN ('scheduled','submitted','success','returned','cancelled')
  ),
  -- Kept verbatim. The normalised reason below is a lossy projection, and a
  -- chargeback is argued from the original code.
  return_code TEXT,
  return_reason TEXT CHECK (return_reason IS NULL OR return_reason IN (
    'insufficient_funds','account_closed','mandate_expired','technical','unknown'
  )),
  -- 'lms' means we recommended and the lender presented. The distinction
  -- decides whether a presentation with no outcome is our bug or theirs.
  executor TEXT NOT NULL DEFAULT 'rail' CHECK (executor IN ('rail','lms')),
  -- The attribution edge, and the load-bearing column in this table. Without
  -- it a re-presentment that cures cannot be credited to the decision that
  -- caused it, and represent_mandate becomes an action the learning loop can
  -- never evaluate.
  decision_id TEXT REFERENCES treatment_decisions(id) ON DELETE SET NULL,
  payment_event_id TEXT REFERENCES payment_events(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- One row per attempt at a cycle. Makes a retried executor idempotent and
-- makes the presentation limit a countable thing rather than a guess.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mandate_presentations_attempt
  ON mandate_presentations (mandate_id, presented_for, attempt_no);
CREATE INDEX IF NOT EXISTS idx_mandate_presentations_tenant_id
  ON mandate_presentations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mandate_presentations_account
  ON mandate_presentations (account_id, presented_for DESC);
-- The settlement poller's claim: submitted and not yet resolved.
CREATE INDEX IF NOT EXISTS idx_mandate_presentations_open
  ON mandate_presentations (status, scheduled_at)
  WHERE status IN ('scheduled','submitted');
-- Attribution joins the other way too, from decision to what it produced.
CREATE INDEX IF NOT EXISTS idx_mandate_presentations_decision
  ON mandate_presentations (decision_id) WHERE decision_id IS NOT NULL;

-- Append-only authority-matrix log (P4). Every invocation is written,
-- including escalate and including shadow runs that never posted a rupee.
CREATE TABLE IF NOT EXISTS authority_decisions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  dispute_id TEXT REFERENCES disputes(id) ON DELETE SET NULL,
  fee_type TEXT NOT NULL,
  asked_amount numeric(14,2),
  mode TEXT NOT NULL,
  feature_schema_version TEXT NOT NULL,
  features jsonb NOT NULL DEFAULT '{}'::jsonb,
  verdict TEXT NOT NULL,
  approved_amount numeric(14,2),
  cap_amount numeric(14,2),
  reason TEXT,
  reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
  talk_track TEXT,
  latency_ms INTEGER,
  enacted boolean NOT NULL DEFAULT false,
  enacted_at timestamptz,
  enacted_ref TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_authority_decisions_fee_type CHECK (
    fee_type IN ('late_fee','bounce_charge','settlement','restructuring')
  ),
  CONSTRAINT ck_authority_decisions_mode CHECK (mode IN ('off','shadow','live')),
  CONSTRAINT ck_authority_decisions_verdict CHECK (
    verdict IN ('auto_approve','cap_inr','escalate')
  )
);
CREATE INDEX IF NOT EXISTS idx_authority_decisions_tenant_id ON authority_decisions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_authority_decisions_customer_id ON authority_decisions(customer_id);
CREATE INDEX IF NOT EXISTS idx_authority_decisions_interaction
  ON authority_decisions (interaction_id, created_at DESC)
  WHERE interaction_id IS NOT NULL;


-- Book-level allocation: the marginal value of one more agent-hour -----------
-- Per-account argmax is a local decision. Solving the whole book against fixed
-- capacity yields shadow prices, and feeding those back as the cost term makes
-- every local decision globally optimal without anybody writing a threshold
-- down: a field visit costs its ledger price on a quiet Tuesday and four times
-- that when the vans are full, so the ladder throttles itself.
CREATE TABLE IF NOT EXISTS capacity_duals (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  -- The borrower's local day the plan is for, not the day it was solved.
  plan_date date NOT NULL,
  resource TEXT NOT NULL,
  capacity numeric(14,2) NOT NULL,
  -- What the solver expects to consume at this price. "High price, under
  -- capacity" and "high price, exactly at capacity" mean different things and
  -- only the second is a scarcity signal.
  demand numeric(14,2) NOT NULL DEFAULT 0,
  -- Rupees of expected recovery forgone by giving up one unit. Zero means the
  -- resource is not binding -- the common case, and the one that must not read
  -- as "free".
  dual_price numeric(14,4) NOT NULL DEFAULT 0,
  accounts INTEGER NOT NULL DEFAULT 0,
  converged boolean NOT NULL DEFAULT false,
  iterations INTEGER NOT NULL DEFAULT 0,
  solved_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_capacity_duals_day
  ON capacity_duals (tenant_id, plan_date, resource);
CREATE INDEX IF NOT EXISTS idx_capacity_duals_tenant_id ON capacity_duals(tenant_id);

-- ---------------------------------------------------------------------------
-- Model registry -- the champion/challenger ledger (design note S15).
-- ---------------------------------------------------------------------------
-- Promotion gated on holdout lift, never on offline metrics alone. This table
-- is where that gate leaves its evidence: a champion row cannot exist without
-- the estimate that justified it, so "why is this model serving?" has an answer
-- that is not a Slack thread.
--
-- The registry records and gates; it does not serve. models.load_* stays a pure
-- file read with no database on the scoring path, and promotion is what copies
-- a challenger artifact into the serving location. artifact_sha is what makes
-- that honest: it detects a file swapped underneath a promotion.
CREATE TABLE IF NOT EXISTS treatment_model_registry (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  target TEXT NOT NULL CHECK (target IN ('reach','timing','uplift')),
  -- The artifact's own version string, and the sha256 of the file it came from.
  version TEXT NOT NULL,
  artifact_sha TEXT NOT NULL,
  artifact_path TEXT,
  -- 'challenger' is where everything starts. Nothing is born a champion.
  status TEXT NOT NULL DEFAULT 'challenger'
    CHECK (status IN ('challenger','champion','retired','rejected')),
  -- Which book it was fitted on. A simulated artifact can be registered and
  -- inspected; promoting one is refused.
  corpus TEXT NOT NULL DEFAULT 'live',
  n_samples INTEGER NOT NULL DEFAULT 0,
  control_n INTEGER NOT NULL DEFAULT 0,
  segments_promoted INTEGER NOT NULL DEFAULT 0,
  -- The artifact's metrics block, verbatim.
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- The holdout / OPE evidence that justified the promotion, verbatim from
  -- evaluate_policy. Null on a challenger that has not been evaluated.
  evaluation jsonb,
  registered_at timestamptz NOT NULL DEFAULT now(),
  promoted_at timestamptz,
  promoted_by TEXT,
  retired_at timestamptz,
  reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
-- One champion per target per tenant, enforced by the database rather than by
-- the promotion code remembering to demote. Two champions is not a state the
-- serving path can express, so it must not be a state the ledger can hold.
CREATE UNIQUE INDEX IF NOT EXISTS uq_treatment_model_champion
  ON treatment_model_registry (tenant_id, target)
  WHERE status = 'champion';
CREATE UNIQUE INDEX IF NOT EXISTS uq_treatment_model_version
  ON treatment_model_registry (tenant_id, target, version, artifact_sha);
CREATE INDEX IF NOT EXISTS idx_treatment_model_registry_tenant_id
  ON treatment_model_registry(tenant_id);
CREATE INDEX IF NOT EXISTS idx_treatment_model_registry_target
  ON treatment_model_registry(tenant_id, target, registered_at DESC);
