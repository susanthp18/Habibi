-- Catalog shared by accounts (what the customer holds) and the upsell engine
-- (what we may offer). The NBO columns below are what let a recommender rank
-- products without hardcoding a list in a tool description: `ticket_min/max`
-- bound the suggested amount, `roi_numeric` and `margin_score` make offers
-- comparable, `channels` keeps a branch-only product off the voice bot, and
-- `is_active` is the kill switch that does not need a deploy.
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  ticket_min numeric(14,2),
  ticket_max numeric(14,2),
  roi TEXT,
  category TEXT,
  family TEXT,
  description TEXT,
  -- roi TEXT stays for display ("10.75% p.a."); roi_numeric is the rankable one.
  roi_numeric numeric(6,3),
  tenor_months_min INTEGER,
  tenor_months_max INTEGER,
  margin_score numeric(5,3) NOT NULL DEFAULT 0.500,
  is_active boolean NOT NULL DEFAULT true,
  channels TEXT[] NOT NULL DEFAULT ARRAY['voice','whatsapp','agent']::TEXT[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_products_tenant_id ON products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active);

CREATE TABLE IF NOT EXISTS product_eligibility_rules (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  conditions jsonb NOT NULL DEFAULT '{}'::jsonb,
  effective_from timestamptz,
  effective_to timestamptz,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_product_eligibility_rules_product_id ON product_eligibility_rules(product_id);

CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  assigned_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  phone_primary TEXT,
  phone_alt TEXT,
  email TEXT,
  address TEXT,
  timezone TEXT,
  language TEXT,
  preferred_window TEXT,
  dnd boolean NOT NULL DEFAULT false,
  segment TEXT,
  risk TEXT NOT NULL CHECK (risk IN ('critical','high','medium','low')),
  risk_score INTEGER,
  last_contact_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant_id ON customers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customers_assigned_user_id ON customers(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_customers_risk ON customers(risk);

CREATE TABLE IF NOT EXISTS customer_notes (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  author_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  interaction_id TEXT,
  text TEXT NOT NULL,
  pinned boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_notes_customer_id ON customer_notes(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_notes_author_user_id ON customer_notes(author_user_id);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL REFERENCES products(id),
  apr numeric(7,3),
  sanctioned_amount numeric(14,2),
  outstanding numeric(14,2) NOT NULL DEFAULT 0,
  minimum_due numeric(14,2),
  dpd INTEGER NOT NULL DEFAULT 0,
  bucket TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  opened_on timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_accounts_customer_id ON accounts(customer_id);
CREATE INDEX IF NOT EXISTS idx_accounts_product_id ON accounts(product_id);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);
-- Identity verification resolves a customer from the last 4 account digits
-- (capture.find_customer_by_account_tail). Without these expression indexes
-- the lookup is a full scan that recomputes RIGHT/regexp_replace per row, on
-- the latency-critical path of a live call.
CREATE INDEX IF NOT EXISTS idx_accounts_digit_tail4
  ON accounts ((RIGHT(regexp_replace(id, '[^0-9]', '', 'g'), 4)));
CREATE INDEX IF NOT EXISTS idx_accounts_id_tail4
  ON accounts ((RIGHT(id, 4)));
-- The decision engine's book sweep claims "active and delinquent" and walks it
-- by id so it can resume from a cursor. Ordering on id with delinquency as the
-- partial predicate is what that scan wants; idx_accounts_status alone makes it
-- read every active account in the book to find the overdue ones.
CREATE INDEX IF NOT EXISTS idx_accounts_delinquent
  ON accounts (id) WHERE status = 'active' AND dpd > 0;

CREATE TABLE IF NOT EXISTS ledger_entries (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('charge','payment','fee','adjustment','waiver')),
  description TEXT,
  amount numeric(14,2) NOT NULL,
  balance numeric(14,2),
  invoice_id TEXT,
  posted_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_account_id ON ledger_entries(account_id);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_posted_at ON ledger_entries(posted_at);

CREATE TABLE IF NOT EXISTS emi_installments (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  installment_index INTEGER NOT NULL,
  due_date timestamptz NOT NULL,
  amount numeric(14,2) NOT NULL,
  paid_on timestamptz,
  paid_amount numeric(14,2),
  status TEXT NOT NULL CHECK (status IN ('paid','upcoming','overdue','partial')),
  balance_carried numeric(14,2),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_emi_installments_account_id ON emi_installments(account_id);
CREATE INDEX IF NOT EXISTS idx_emi_installments_status ON emi_installments(status);

-- NACH/UPI/ECS bounce (or later paid/reversal) is a first-class event. The
-- row *is* the collections case: open/in_progress project into work_items.
-- payment_intent_id is filled after the pay-link is created; the FK is
-- deferred until payment_intents exists (sql/90_deferred_fks.sql).
CREATE TABLE IF NOT EXISTS payment_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  emi_installment_id TEXT REFERENCES emi_installments(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK (kind IN ('bounce')),
  reason TEXT NOT NULL CHECK (reason IN (
    'insufficient_funds','account_closed','mandate_expired','technical','unknown'
  )),
  amount numeric(14,2) NOT NULL,
  bounce_fee numeric(14,2),
  source TEXT NOT NULL CHECK (source IN ('nach','upi','ecs','sandbox','webhook')),
  source_ref TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open','in_progress','cured','suppressed')),
  first_touch_at timestamptz,
  first_touch_channel TEXT CHECK (
    first_touch_channel IS NULL OR first_touch_channel IN ('whatsapp','sms','voice')
  ),
  next_voice_at timestamptz,
  next_credit_at timestamptz,
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  payment_intent_id TEXT,
  suppression_reason TEXT,
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_events_source_ref
  ON payment_events (tenant_id, source, source_ref);
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_events_open_emi
  ON payment_events (account_id, emi_installment_id)
  WHERE kind = 'bounce'
    AND status IN ('open','in_progress')
    AND emi_installment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_payment_events_tenant_id ON payment_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_customer_occurred
  ON payment_events (customer_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_payment_events_status_voice
  ON payment_events (status, next_voice_at);
CREATE INDEX IF NOT EXISTS idx_payment_events_account_id ON payment_events(account_id);

