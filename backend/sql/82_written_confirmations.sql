-- What a written confirmation said, which call holds it, and the callback and
-- dispute confirmations as owed rows instead of best-effort sends.
--
-- promise_reminders
--   body                       the copy as transmitted: the composed text, or
--                              the approved template rendered with the values
--                              sent. A change of terms held for the end of a
--                              call is skipped when its terms are the ones
--                              already sent.
--   after_call_interaction_id  the live call a changed confirmation waits for.
--                              Filing that call releases it; filing another
--                              call the promise was touched on does not.
--
-- written_followups: one row per booking or reference that owes the customer
-- a written copy (callback booked, dispute logged). The unique (kind,
-- related_id) is what makes "once" atomic: two tool calls racing for the same
-- booking insert one row. A bot_worker stage sends it at send time, after the
-- contact policy admits it; a refusal that expires (messaging hours) moves
-- scheduled_at instead of dropping the copy.
--   status  scheduled -> queued (handed to WhatsApp, or an SMS lease)
--           -> sent (provider accepted) | failed (with failure_reason)

ALTER TABLE promise_reminders ADD COLUMN IF NOT EXISTS body TEXT;
ALTER TABLE promise_reminders ADD COLUMN IF NOT EXISTS after_call_interaction_id TEXT
  REFERENCES interactions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS written_followups (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK (kind IN ('hardship_ack','dispute_ref','callback_confirm')),
  related_id TEXT NOT NULL,
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','queued','sent','failed')),
  channel TEXT CHECK (channel IS NULL OR channel IN ('whatsapp','sms')),
  scheduled_at timestamptz NOT NULL DEFAULT now(),
  attempted_at timestamptz,
  message_id TEXT,
  failure_reason TEXT,
  sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, related_id)
);
CREATE INDEX IF NOT EXISTS idx_written_followups_due
  ON written_followups (scheduled_at) WHERE status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_written_followups_handed
  ON written_followups (attempted_at) WHERE status = 'queued';
