CREATE TABLE IF NOT EXISTS consent_records (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL UNIQUE REFERENCES customers_pii(id) ON DELETE CASCADE,
  dnd_registry boolean NOT NULL DEFAULT false,
  expires_at timestamptz,
  allowed_days TEXT,
  allowed_hours TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Consent is per channel AND per purpose. "May we use WhatsApp?" and "may we
-- use WhatsApp to sell them something?" are two questions, and DPDP purpose
-- limitation says the answer to the first is not the answer to the second.
-- Rows default to 'servicing'; promotional contact requires its own row, and
-- its absence is a refusal rather than a fallback.
CREATE TABLE IF NOT EXISTS channel_consents (
  id TEXT PRIMARY KEY,
  consent_id TEXT NOT NULL REFERENCES consent_records(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  purpose TEXT NOT NULL DEFAULT 'servicing' CHECK (purpose IN ('servicing','promotional')),
  status TEXT NOT NULL CHECK (status IN ('opted_in','opted_out','dnd','expired')),
  source TEXT,
  weekly_frequency_cap INTEGER,
  used_this_week INTEGER NOT NULL DEFAULT 0,
  captured_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ux_channel_consents_consent_channel_purpose UNIQUE (consent_id, channel, purpose)
);
CREATE INDEX IF NOT EXISTS idx_channel_consents_consent_id ON channel_consents(consent_id);
CREATE INDEX IF NOT EXISTS idx_channel_consents_purpose ON channel_consents(consent_id, purpose);

CREATE TABLE IF NOT EXISTS optout_events (
  id TEXT PRIMARY KEY,
  consent_id TEXT NOT NULL REFERENCES consent_records(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat','all')),
  source TEXT NOT NULL,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','bot','customer','system','regulator')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  note TEXT,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_optout_events_consent_id ON optout_events(consent_id);

-- Append-only contact ledger (P6). Caps are derived from this, not from
-- channel_consents.used_this_week (that column is a cache). Denied attempts
-- are logged; they do not increment the daily budget.
CREATE TABLE IF NOT EXISTS contact_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat','field')),
  direction TEXT NOT NULL DEFAULT 'outbound' CHECK (direction IN ('outbound','inbound')),
  purpose TEXT NOT NULL CHECK (purpose IN ('outreach','statutory','in_session')),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','bot','system','agency')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('allowed','denied')),
  reason TEXT,
  session_key TEXT,
  source TEXT,
  related_id TEXT,
  touch_counted boolean NOT NULL DEFAULT false,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  policy_binding jsonb,
  policy_binding_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_contact_events_tenant_id ON contact_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contact_events_customer_occurred
  ON contact_events (customer_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_contact_events_session
  ON contact_events (customer_id, session_key, occurred_at);
CREATE INDEX IF NOT EXISTS idx_contact_events_related
  ON contact_events (customer_id, source, related_id);

-- Atomic daily budget. outreach_sessions counts touches that consume the cap
-- (outreach + statutory). Locked FOR UPDATE inside admit().
CREATE TABLE IF NOT EXISTS contact_day_counters (
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  local_date DATE NOT NULL,
  outreach_sessions INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (customer_id, local_date)
);


-- Regulatory rules as versioned data ------------------------------------------
-- The calling window, the caps and the cooling-off period lived as module
-- constants in contact_policy.py, which cannot answer the question a regulator
-- actually asks: not "would you dial at 19:15?" but "why *did* you, last
-- March?". A constant has no effective date, so the only available answer was
-- "our current code says we wouldn't have", which is not an answer.
--
-- As rows with a validity window, two rule sets can be in force at different
-- times and every decision records which one approved it. A rule change then
-- becomes a backfill rather than a fresh start, and a client can tighten policy
-- without a model deploy.
CREATE TABLE IF NOT EXISTS policy_rule_sets (
  id TEXT PRIMARY KEY,
  -- Null means statutory: it binds every tenant and no tenant may edit it. A
  -- client rule set may only ever be stricter.
  tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
  scope TEXT NOT NULL CHECK (scope IN ('statutory','client','product')),
  product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  -- What a regulator would call it. 'RBI/2026-27/230', not 'v7'.
  label TEXT NOT NULL,
  effective_from timestamptz NOT NULL,
  -- Null means in force. A rule set is never edited once effective; it is
  -- superseded, and the superseded row keeps answering "what was in force in
  -- March".
  effective_to timestamptz,
  notes TEXT,
  published_at timestamptz NOT NULL DEFAULT now(),
  published_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  approved_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  publication_state TEXT NOT NULL DEFAULT 'draft' CHECK (
    publication_state IN ('draft','pending_approval','published','rejected')
  ),
  changed_rules TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_policy_rule_sets_window CHECK (
    effective_to IS NULL OR effective_to > effective_from
  ),
  CONSTRAINT ck_policy_rule_sets_maker_checker CHECK (
    published_by_user_id IS NULL
    OR approved_by_user_id IS NULL
    OR published_by_user_id <> approved_by_user_id
  ),
  CONSTRAINT ck_policy_rule_sets_statutory CHECK (
    (scope = 'statutory') = (tenant_id IS NULL)
  ),
  CONSTRAINT ck_policy_rule_sets_product CHECK (
    (scope = 'product') = (product_id IS NOT NULL)
  )
);
-- COALESCE because a null tenant is "everyone" and a null product is "all
-- products", and Postgres would otherwise treat two statutory v1 rows as
-- distinct.
CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_rule_sets_version
  ON policy_rule_sets (COALESCE(tenant_id,''), scope, COALESCE(product_id,''), version);
-- The resolver's only read: every set that could be in force at an instant.
CREATE INDEX IF NOT EXISTS idx_policy_rule_sets_effective
  ON policy_rule_sets (scope, effective_from DESC);

CREATE TABLE IF NOT EXISTS policy_rule_kinds (
  kind TEXT PRIMARY KEY,
  params_schema TEXT NOT NULL,
  tighten TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO policy_rule_kinds (kind, params_schema, tighten) VALUES
  ('calling_window', 'calling_window.v1', 'strict_only'),
  ('daily_cap', 'daily_cap.v1', 'strict_only'),
  ('weekly_cap', 'weekly_cap.v1', 'strict_only'),
  ('cooling_off', 'cooling_off.v1', 'strict_only'),
  ('bucket_actions', 'bucket_actions.v1', 'strict_only'),
  ('mandate_presentation_limit', 'mandate_presentation_limit.v1', 'strict_only'),
  ('mandate_return_action', 'mandate_return_action.v1', 'strict_only'),
  ('field_prerequisites', 'field_prerequisites.v1', 'strict_only'),
  ('recording_retention', 'recording_retention.v1', 'strict_only'),
  ('visit_intimation', 'visit_intimation.v1', 'strict_only'),
  ('suppression_state', 'suppression_state.v1', 'strict_only'),
  ('ratio_ceiling', 'ratio_ceiling.v1', 'strict_only'),
  ('assignment_check', 'assignment_check.v1', 'strict_only'),
  ('channel_scrub', 'channel_scrub.v1', 'strict_only'),
  ('non_discretionary_notice', 'non_discretionary_notice.v1', 'strict_only')
ON CONFLICT (kind) DO NOTHING;

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS policy_rules (
  id TEXT PRIMARY KEY,
  rule_set_id TEXT NOT NULL REFERENCES policy_rule_sets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL REFERENCES policy_rule_kinds(kind),
  -- Null means every channel. A calling window is per-channel; a daily cap is
  -- across all of them, and saying that with null rather than a sentinel keeps
  -- the resolver from having to know which is which.
  channel TEXT CHECK (channel IS NULL OR channel IN (
    'voice','whatsapp','sms','email','chat','field'
  )),
  params jsonb NOT NULL DEFAULT '{}'::jsonb,
  rule_id TEXT NOT NULL,
  rule_version INTEGER NOT NULL,
  citation TEXT NOT NULL CHECK (length(btrim(citation)) > 0),
  params_schema TEXT NOT NULL,
  effective tstzrange NOT NULL,
  scope_key TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT excl_policy_rules_scope_rule_effective EXCLUDE USING gist (
    scope_key WITH =,
    rule_id WITH =,
    effective WITH &&
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_rules_kind
  ON policy_rules (rule_set_id, kind, COALESCE(channel,''));
CREATE INDEX IF NOT EXISTS idx_policy_rules_set ON policy_rules (rule_set_id);


-- Delivery receipts, as an event log rather than a status ---------------------
-- The reach estimator needs P(an attempt reaches a human) by channel, hour and
-- borrower. Three of those were already available; the fourth was thrown away.
--
-- Meta's sent / delivered / read callbacks already arrive and already update
-- messages.delivery_status, correctly refusing to let a late "sent" drag an
-- already-read message backwards. But that column is a *current state*: a
-- message that went sent -> delivered -> read leaves only "read", and the
-- moment it was read -- the fact that separates a borrower reachable at 09:00
-- from one reachable at all -- is overwritten and gone. Twilio SMS had no
-- receipts at all; the SID was logged and dropped.
--
-- One row per transition, with the instant it happened. That is what makes a
-- hazard fittable instead of a ratio.
--
-- No new linkage to the attempt ledger: contact_events.related_id already
-- carries the message id for WhatsApp outbound and idx_contact_events_related
-- indexes it. Two keys for one relationship is two answers to one question.
CREATE TABLE IF NOT EXISTS contact_delivery_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('whatsapp','sms','email','voice')),
  provider TEXT NOT NULL,
  -- A Meta wamid or a Twilio SID. What a replayed webhook is deduplicated on.
  provider_ref TEXT,
  -- FK deferred to 90_deferred_fks.sql: `messages` is created in
  -- 04_interactions.sql, and sql/*.sql is applied in filename order — so
  -- an inline REFERENCES here fails on every fresh build.
  message_id TEXT,
  -- Mirrors contact_events.related_id.
  related_id TEXT,
  state TEXT NOT NULL CHECK (state IN (
    'queued','sent','delivered','read','failed','undelivered'
  )),
  reason TEXT,
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
-- Replayed webhooks are normal, not exceptional -- Meta and Twilio both retry.
-- One row per (provider_ref, state) makes a replay a no-op rather than a second
-- observation the reach model would count twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_delivery_events_transition
  ON contact_delivery_events (provider, provider_ref, state)
  WHERE provider_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contact_delivery_events_tenant_id
  ON contact_delivery_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contact_delivery_events_customer
  ON contact_delivery_events (customer_id, channel, occurred_at);
CREATE INDEX IF NOT EXISTS idx_contact_delivery_events_related
  ON contact_delivery_events (related_id) WHERE related_id IS NOT NULL;

-- W4: consent overlay, endpoint ownership, window authorisations, DPDP rights
CREATE TABLE IF NOT EXISTS consent_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  endpoint TEXT,
  channel TEXT NOT NULL CHECK (channel IN (
    'voice','whatsapp','sms','email','chat','field','all'
  )),
  purpose TEXT NOT NULL CHECK (purpose IN ('servicing','promotional','all')),
  verb TEXT NOT NULL CHECK (verb IN ('withdraw','restrict','expire','opt_out')),
  source TEXT NOT NULL,
  evidence_ref TEXT,
  captured_at timestamptz NOT NULL DEFAULT now(),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN (
    'human','bot','customer','system','regulator'
  )),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_consent_events_customer
  ON consent_events (customer_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS endpoint_ownership (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  endpoint TEXT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN (
    'voice','whatsapp','sms','email','chat'
  )),
  slot TEXT NOT NULL CHECK (slot IN ('primary','alt','other')),
  state TEXT NOT NULL CHECK (state IN ('unverified','verified','revoked')),
  source TEXT NOT NULL DEFAULT 'system',
  evidence_ref TEXT,
  verified_at timestamptz,
  revoked_at timestamptz,
  revoked_reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_endpoint_ownership UNIQUE (tenant_id, endpoint, channel)
);
CREATE INDEX IF NOT EXISTS idx_endpoint_ownership_customer
  ON endpoint_ownership (customer_id, state);

CREATE TABLE IF NOT EXISTS window_authorisations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  channel TEXT NOT NULL CHECK (channel IN (
    'voice','whatsapp','sms','email','chat','field'
  )),
  start_hour INTEGER NOT NULL,
  end_hour INTEGER NOT NULL,
  source TEXT NOT NULL,
  citation TEXT,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_window_authorisations_hours CHECK (
    start_hour >= 0 AND start_hour < 24
    AND end_hour > start_hour AND end_hour <= 24
  )
);
CREATE INDEX IF NOT EXISTS idx_window_authorisations_customer
  ON window_authorisations (customer_id, channel);

CREATE TABLE IF NOT EXISTS subject_requests (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  kind TEXT NOT NULL CHECK (kind IN ('access','correction','erasure','grievance')),
  state TEXT NOT NULL CHECK (state IN (
    'received','verified','in_progress','fulfilled','refused','escalated'
  )),
  received_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz,
  due_at timestamptz NOT NULL,
  fulfilled_at timestamptz,
  evidence_ref TEXT,
  owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  escalated_to_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  note TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_subject_requests_slo CHECK (
    due_at <= received_at + interval '90 days'
  )
);
CREATE INDEX IF NOT EXISTS idx_subject_requests_due
  ON subject_requests (tenant_id, due_at)
  WHERE state NOT IN ('fulfilled','refused');

CREATE TABLE IF NOT EXISTS subject_request_events (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES subject_requests(id) ON DELETE CASCADE,
  state TEXT NOT NULL,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  note TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_subject_request_events_request
  ON subject_request_events (request_id, created_at);

CREATE TABLE IF NOT EXISTS erasure_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE RESTRICT,
  request_id TEXT NOT NULL REFERENCES subject_requests(id) ON DELETE RESTRICT,
  cancelled_plans INTEGER NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
