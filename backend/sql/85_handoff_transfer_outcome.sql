-- The Hub's case: what became of the transferred caller, and the person's own
-- wrap-up words.
--
-- transfer_outcome: a Voice Studio agent's transfer rings the callback line;
-- the engine reports at the end of the run whether it answered. 'ringing'
-- while that is unknown, then 'connected' (the engine bridged the caller and
-- its own leg ended) or 'not_connected' (nobody answered, the line was busy,
-- or the caller hung up first); 'no_line' when no callback line is set up, so
-- nothing was rung. NULL: handoffs not made by a call transfer (a WhatsApp
-- escalation, a supervisor's takeover, a fleet hop) or made before this column.
--
-- wrap_up_notes: what the person who closed the case wrote. The interaction's
-- summary is the conversation's, filed when the call ends; the two used to
-- share one column, and whichever was written last replaced the other.
ALTER TABLE interaction_handoffs
  ADD COLUMN IF NOT EXISTS transfer_outcome TEXT
  CHECK (transfer_outcome IN ('ringing', 'connected', 'not_connected', 'no_line'));
ALTER TABLE interaction_handoffs ADD COLUMN IF NOT EXISTS wrap_up_notes TEXT;
