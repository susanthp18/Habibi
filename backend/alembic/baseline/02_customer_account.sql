CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  ticket_min numeric(14,2),
  ticket_max numeric(14,2),
  roi TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

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

