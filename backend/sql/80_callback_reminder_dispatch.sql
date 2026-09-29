-- Callback reminders are delivered by the system, or recorded as not sent.
--
-- Nothing read `callback_reminders` to deliver them. `add_callback_reminder`
-- took `status: "sent"` from the client, stamped `sent_at`, moved the callback
-- to `reminded` and logged "Callback reminder sent" without contacting anyone.
-- `callback_reminders.py` (a bot_worker stage) now sends them, and only it
-- writes `sent`.
--
-- attempted_at    when the system handed the reminder to a provider. For SMS
--                 it is also the lease: taken before the carrier call, so a
--                 rollback cannot send twice (sql/35 is the same rule).
-- message_id      the WhatsApp message it went out as; `sent` once
--                 whatsapp_outbound's job succeeds.
-- failure_reason  why it was not sent.
--
-- A `sent` row with no attempt was a button press, not a delivery: no code
-- could send one before this. Relabelled, not deleted, and the predicate keeps
-- the UPDATE safe to re-run once the system is writing real `sent` rows.

ALTER TABLE callback_reminders ADD COLUMN IF NOT EXISTS attempted_at timestamptz;
ALTER TABLE callback_reminders ADD COLUMN IF NOT EXISTS message_id TEXT;
ALTER TABLE callback_reminders ADD COLUMN IF NOT EXISTS failure_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_callback_reminders_open
  ON callback_reminders (scheduled_at) WHERE status IN ('scheduled', 'queued');

UPDATE callback_reminders
   SET status = 'failed', failure_reason = 'manual_record'
 WHERE status = 'sent' AND attempted_at IS NULL;
