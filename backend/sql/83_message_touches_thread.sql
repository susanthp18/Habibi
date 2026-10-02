-- A thread's watermark follows its messages.
--
-- conversations.updated_at is what the Inbox list's delta poll reads
-- (?updatedAfter=). A message that is written or changes state changes what
-- the list shows for its thread -- the last message, how many of the
-- customer's await a reply (only a reply the provider took counts), the SLA.
-- Each writer used to move the watermark by hand, and two never did: the SMS
-- delivery callback and the bot's own send. Their threads kept a stale count
-- and SLA in the list until a full refresh. Owned here, once, for every writer.
CREATE OR REPLACE FUNCTION touch_message_conversation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE conversations SET updated_at = now() WHERE id = NEW.conversation_id;
  RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS trg_messages_touch_conversation ON messages;
CREATE TRIGGER trg_messages_touch_conversation
  AFTER INSERT OR UPDATE ON messages
  FOR EACH ROW
  WHEN (NEW.conversation_id IS NOT NULL)
  EXECUTE FUNCTION touch_message_conversation();
