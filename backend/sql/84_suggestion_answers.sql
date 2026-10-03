-- The customer message a thread's stored knowledge-base passages answer.
--
-- The Inbox shows a thread's stored passages when it is opened. Without the
-- message they were found for, it could not tell that the customer has
-- written since, and a viewer who never searches (read-only) saw them as
-- current indefinitely. A search replaces the set whole, so every row of a
-- set carries the same message. NULL: not found for a message (a call's
-- passages) or stored before this column -- shown as not answering the latest.
ALTER TABLE ai_response_suggestions
  ADD COLUMN IF NOT EXISTS answers_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL;
