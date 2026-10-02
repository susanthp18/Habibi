/**
 * The inbox's wire types: the API's own response models (wire/generated.ts).
 *
 * This file used to be a hand-written copy, and it had drifted -- it dropped
 * the reason the rail's "Not contactable" was for, so the rail could only ever
 * say "no" without saying why.
 */
import type { z } from "zod";

import type {
  ConversationResponse,
  ConversationSummaryResponse,
  InboxMessageResponse,
  InboxSystemEventResponse,
  InboxThreadContextResponse,
} from "@/api/wire/generated";

/** One row of the list: no transcript. */
export type ThreadSummary = z.infer<typeof ConversationSummaryResponse>;
/** The open thread: transcript, suggestions and customer context. */
export type Thread = z.infer<typeof ConversationResponse>;
export type ThreadContext = z.infer<typeof InboxThreadContextResponse>;
export type Message = z.infer<typeof InboxMessageResponse>;
export type SystemEvent = z.infer<typeof InboxSystemEventResponse>;
export type ThreadItem = Message | SystemEvent;

export type InboxChannel = ThreadSummary["channel"];
/** Stored conversation status — "mine" is derived (assignedUserId === me). */
export type ThreadStatus = ThreadSummary["status"];
export type SlaLevel = ThreadSummary["sla"];
export type Sentiment = ThreadSummary["sentiment"];
export type MessageDeliveryStatus = NonNullable<Message["delivery"]>;
/** The list's server-side views (`GET /conversations?view=`). */
export type InboxView = "mine" | "others" | ThreadStatus;

export const SENDERS = ["customer", "bot", "agent", "system"] as const;
export type Sender = (typeof SENDERS)[number];
