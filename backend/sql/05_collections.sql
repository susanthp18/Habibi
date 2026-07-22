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
  scheduled_at timestamptz,
  sent_at timestamptz,
  status TEXT NOT NULL CHECK (status IN ('off','queued','scheduled','sent','acknowledged','failed')),
  provider_delivery_id TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_promise_reminders_promise_id ON promise_reminders(promise_id);

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
  name TEXT NOT NULL,
  doc_type TEXT NOT NULL,
  preview_lines jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

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
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((promise_id IS NOT NULL)::int + (lead_id IS NOT NULL)::int = 1)
);
CREATE INDEX IF NOT EXISTS idx_followups_customer_id ON followups(customer_id);
CREATE INDEX IF NOT EXISTS idx_followups_promise_id ON followups(promise_id);

