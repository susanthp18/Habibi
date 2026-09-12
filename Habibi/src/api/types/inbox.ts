/**
 * Domain / wire types for the inbox surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

// Mirrors the conversations.channel CHECK constraint (sql/04_interactions.sql).
// Narrower than the database, the inbox drops threads it was meant to show.
export type Channel = "whatsapp" | "sms" | "email" | "chat" | "voice";
export type Sender = "customer" | "bot" | "agent" | "system";
/** Stored conversation status — "mine" is derived (assignedUserId === me). */
export type ThreadStatus = "bot" | "needs_human" | "escalated" | "assigned";
export type SlaLevel = "ok" | "warn" | "breach";
export type Sentiment = "positive" | "neutral" | "negative";
// "pending" = queued by the API, not yet accepted by the provider. It must be
// distinguishable from a delivered message: rendering both as "no tick" is how
// an agent spent six minutes replying to a customer who saw nothing.
export type DeliveryStatus = "pending" | "sent" | "delivered" | "read" | "failed";
export interface Message {
  id: string;
  sender: Sender;
  text: string;
  time: string; // "3:41 PM"
  delivery?: DeliveryStatus; // for bot/agent
}
export interface SystemEvent {
  id: string;
  kind: "system";
  text: string;
  time: string;
}
export type ThreadItem = Message | SystemEvent;
export interface ThreadContext {
  riskLevel: "High" | "Medium" | "Low";
  contactableNow: boolean;
  contactWindow: string;
  outstanding: number;
  outstandingAging: string;
  nextEmiDate: string;
  nextEmiAmount: number;
  lastPromise: {
    amount: number;
    date: string;
    status: "Kept" | "Broken" | "Pending" | "Partial";
  } | null;
  openDisputes: { id: string; summary: string }[];
  recentInteractions: {
    id: string;
    kind: "call" | "chat";
    summary: string;
    when: string;
    sentiment: Sentiment;
  }[];
}
export interface Thread {
  id: string;
  customer: string;
  /** CRM customer id for Customer 360 / PTP / dispute deep-links. */
  customerId?: string;
  accountId: string;
  channel: Channel;
  status: ThreadStatus;
  /** Owning agent; Mine filter = assignedUserId === current user. */
  assignedUserId: string | null;
  isMine: boolean;
  /** True while a bot turn is queued/running (WhatsApp auto-reply in flight). */
  botTyping?: boolean;
  /** True while bot/agent outbound WhatsApp send is queued or mid-flight. */
  pendingOutbound?: boolean;
  /** Server watermark for delta polls (`?updatedAfter=`). */
  updatedAt?: string | null;
  sla: SlaLevel;
  unread: number;
  lastTime: string;
  lastPreview: string;
  lastFrom: Sender;
  sentiment: Sentiment;
  handlerBotId?: string | null;
  ragSuggestions: string[];
  /** Optional grounded draft from shared kb_retrieve (same as Test Retrieval). */
  ragDraftAnswer?: string | null;
  messages: ThreadItem[];
  /** Present on GET /conversations/{id} and write responses; the list omits it. */
  context?: ThreadContext | null;
}
