-- What became of the caller when a Voice Studio agent handed the call to a
-- person. The engine bridges the caller to the callback line and its own leg
-- ends, so the handoff outlives the call: the Hub works it as a follow-up case
-- and has to say whether someone already took the call ('callback_line') or
-- nobody could ('no_one_available': call the customer back). NULL: handoffs
-- not made by a transfer (a supervisor's takeover, a fleet hop) or made before
-- this column.
ALTER TABLE interaction_handoffs
  ADD COLUMN IF NOT EXISTS transfer_outcome TEXT
  CHECK (transfer_outcome IN ('callback_line', 'no_one_available'));
