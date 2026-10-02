import { ApiError } from "@/api/config";
import type { InboxChannel } from "@/api/types/inbox";
import { contactRefusalLabel } from "@/components/customer360/ContactabilityPill";
import { channelMeta } from "./meta";

/**
 * Why a reply on this thread can't go out right now, in the operator's words.
 *
 * The gate's own reasons are worded by ContactabilityPill, their one owner;
 * this adds the inbox's reasons and the channel wording the pill (a voice
 * verdict) does not have.
 */
export function replyBlockedWords(
  reason: string | null | undefined,
  channel: InboxChannel,
): string {
  const on = channelMeta[channel].label;
  switch (reason) {
    case "whatsapp_window_closed":
      return "WhatsApp's 24-hour reply window is closed. A free-form reply is only allowed within 24 hours of the customer's last message — reach them on another channel.";
    case "channel_not_supported":
      return `Replies can't be sent on ${on} from the inbox.`;
    case "policy_unavailable":
      return "Contact policy couldn't be checked, so replies are held until it can.";
    case "channel_opted_out":
      return `The customer opted out of ${on}.`;
    case "channel_dnd":
      return `${on} is marked do-not-disturb for this customer.`;
    case "channel_expired":
      return `Consent for ${on} has expired.`;
    default:
      return `Contact policy blocks a reply now: ${contactRefusalLabel(reason ?? null)}.`;
  }
}

const SERVER_WORDS: Record<string, string> = {
  take_over_required: "Take over this conversation before replying.",
  conversation_owner_changed:
    "Someone else took this conversation a moment ago. It now shows who holds it.",
  reassign_requires_supervisor: "Only a supervisor can take a conversation a colleague is holding.",
  return_to_bot_not_allowed: "Only the agent holding this conversation can hand it back.",
  bot_does_not_answer_channel: "No bot answers this channel.",
  whatsapp_missing_recipient: "This customer has no WhatsApp number on file.",
  sms_missing_recipient: "This customer has no phone number for SMS.",
  sms_not_configured: "SMS isn't set up on the server. Ask an admin to configure the SMS provider.",
  empty_message: "Write a message first.",
  conversation_not_found: "This conversation no longer exists.",
  inbox_rag_failed: "Couldn't search the knowledge base.",
};

/**
 * Any inbox write's failure, as one sentence. Never the request line or an
 * internal permission id: an agent used to read
 * `POST /conversations/CV-1/takeover failed: forbidden:perm-supervisor-write`.
 */
export function inboxErrorWords(error: unknown, channel: InboxChannel): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : "The request failed.";
  }
  const code = error.detail.split(":", 1)[0]?.trim() ?? "";
  if (SERVER_WORDS[code]) return SERVER_WORDS[code];
  if (error.status === 403) return "You don't have permission to do that.";
  if (error.status === 429) return "Too many requests — try again in a moment.";
  if (error.status === 409 && /^[a-z_]+$/.test(code)) return replyBlockedWords(code, channel);
  if (error.status >= 500) return "The server couldn't complete that. Try again in a moment.";
  return error.detail || "The request failed.";
}
