-- A reminder SMS is sent outside the transaction that claimed it.
--
-- `promise_fulfillment.process_one_reminder` used to call the carrier while
-- holding `FOR UPDATE` on the reminder row: a commit failure after the send
-- rolled the row back to `queued` and sent the borrower a second SMS; a policy
-- refusal was written as `failed`, which is the word for a carrier error, and
-- the reminder was never tried again.
--
-- `sending_at` is the lease. The drain skips a row that carries one; a row
-- whose lease is older than the sweep window is a send whose outcome was never
-- recorded, and it is marked `failed` for a person rather than retried -- the
-- same rule `whatsapp_outbound_jobs.post_attempted_at` applies, for the same
-- reason: a retry of a possibly-sent message is a second message.
--
-- Catalog-only: nullable column, non-volatile default, no backfill.

ALTER TABLE promise_reminders ADD COLUMN IF NOT EXISTS sending_at timestamptz;
ALTER TABLE promise_reminders ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
