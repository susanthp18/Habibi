-- A due-day reminder for every day a promise is owed, not one per promise.
--
-- A promise paid in parts is owed on each part's day, and a revision moves
-- those days. `uq_promise_reminders_due` allowed one `due` row per promise, so
-- the reminder was written once, for the last day, and never moved: run 88's
-- stayed on 6 Oct after the promise moved to the 7th, and its first part
-- (2 Oct) had none. `promise_fulfillment._sync_due_reminders` now keeps one row
-- per payment day ahead and switches off unsent rows for days no longer owed.
--
-- due_on  the customer's day (IST) the reminder is for; the drain reads the
--         part due that day. Back-filled from scheduled_at, which is 08:15 IST
--         on that day for every row the old code wrote.

ALTER TABLE promise_reminders ADD COLUMN IF NOT EXISTS due_on date;

UPDATE promise_reminders
   SET due_on = (scheduled_at AT TIME ZONE 'Asia/Kolkata')::date
 WHERE kind = 'due' AND due_on IS NULL AND scheduled_at IS NOT NULL;

DROP INDEX IF EXISTS uq_promise_reminders_due;
CREATE UNIQUE INDEX IF NOT EXISTS uq_promise_reminders_due_day
  ON promise_reminders (promise_id, due_on) WHERE kind = 'due';
