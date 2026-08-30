CREATE TABLE IF NOT EXISTS consent_records (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL UNIQUE REFERENCES customers(id) ON DELETE CASCADE,
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
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
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
  created_at timestamptz NOT NULL DEFAULT now()
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
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
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
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_policy_rule_sets_window CHECK (
    effective_to IS NULL OR effective_to > effective_from
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

CREATE TABLE IF NOT EXISTS policy_rules (
  id TEXT PRIMARY KEY,
  rule_set_id TEXT NOT NULL REFERENCES policy_rule_sets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN (
    'calling_window','daily_cap','weekly_cap','cooling_off','bucket_actions',
    'mandate_presentation_limit','mandate_return_action','field_prerequisites',
    'recording_retention','visit_intimation'
  )),
  -- Null means every channel. A calling window is per-channel; a daily cap is
  -- across all of them, and saying that with null rather than a sentinel keeps
  -- the resolver from having to know which is which.
  channel TEXT CHECK (channel IS NULL OR channel IN (
    'voice','whatsapp','sms','email','chat','field'
  )),
  params jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
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
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
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
