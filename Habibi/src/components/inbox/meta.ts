import type { InboxChannel, SlaLevel, ThreadStatus, ThreadSummary } from "@/api/types/inbox";
import { MessageCircle, Mail, MessageSquare, Phone } from "lucide-react";
import type { LozengeProps } from "@/components/ui/lozenge";
import type { TagProps } from "@/components/ui/tag";

type Tone = NonNullable<LozengeProps["tone"]>;
type Hue = NonNullable<TagProps["hue"]>;

/*
 * InboxChannel is a decorative classification, not a status, so the design spec (styles.css) puts it on a Tag
 * (transparent + accent border) rather than a Lozenge — "Decorative Tag used for status"
 * and "Filled tag pills with semantic-looking backgrounds" are both listed as DON'Ts, and
 * the old filled-green WhatsApp pill was reading as a success state it never meant.
 */
export const channelMeta: Record<
  InboxChannel,
  { label: string; icon: typeof MessageCircle; hue: Hue }
> = {
  whatsapp: { label: "WhatsApp", icon: MessageCircle, hue: "green" },
  sms: { label: "SMS", icon: MessageSquare, hue: "blue" },
  email: { label: "Email", icon: Mail, hue: "purple" },
  chat: { label: "Web chat", icon: MessageCircle, hue: "teal" },
  voice: { label: "Voice", icon: Phone, hue: "magenta" },
};

/** Safe lookup — unknown / future channels degrade instead of crashing. */
export function resolveChannelMeta(channel: string | null | undefined) {
  // Own-property check, not `in`: a channel value of "constructor" or
  // "toString" walks the prototype chain and returns a function, which then
  // renders as garbage instead of falling back.
  if (channel && Object.prototype.hasOwnProperty.call(channelMeta, channel)) {
    return channelMeta[channel as InboxChannel];
  }
  return channelMeta.whatsapp;
}

export const slaColor: Record<SlaLevel, string> = {
  ok: "bg-background-success",
  warn: "bg-background-warning",
  breach: "bg-background-danger",
};

export const statusMeta: Record<ThreadStatus | "mine", { label: string; tone: Tone }> = {
  bot: { label: "Bot", tone: "selected" },
  needs_human: { label: "Needs human", tone: "warning" },
  escalated: { label: "Escalated", tone: "danger" },
  assigned: { label: "Assigned", tone: "neutral" },
  mine: { label: "Mine", tone: "success" },
};

/** What the signed-in operator may do to a thread (from `useMe` / `can`). */
export type InboxRights = {
  /** perm-interactions-write: reply, claim an unheld thread, hand your own back. */
  canWrite: boolean;
  /** perm-supervisor-write: take a thread a colleague holds. */
  canReassign: boolean;
  /** perm-collections-write: file a document to the customer's record. */
  canFileDocuments?: boolean;
};

/**
 * Shared handoff / claim state for inbox thread chrome.
 *
 * `needsClaim` disables the composer; `canClaim` is the render condition for
 * the Take-over button. Claiming is what unblocks every state that is not
 * mine -- but only an operator allowed to claim is offered the button: an
 * agent shown "Take over" on a colleague's thread pressed it into a 403 that
 * named an internal permission. Return to bot is for WhatsApp only, the one
 * channel a bot answers.
 */
export function getThreadHandoffState(
  thread: Pick<ThreadSummary, "isMine" | "status" | "channel">,
  rights: InboxRights = { canWrite: false, canReassign: false },
) {
  const needsClaim = !thread.isMine;
  const heldByTeammate = !thread.isMine && thread.status === "assigned";
  const canClaim = needsClaim && rights.canWrite && (!heldByTeammate || rights.canReassign);
  const canReturnToBot =
    rights.canWrite &&
    thread.isMine &&
    thread.channel === "whatsapp" &&
    (thread.status === "assigned" ||
      thread.status === "needs_human" ||
      thread.status === "escalated");
  const botHandling = thread.status === "bot" && !thread.isMine;
  return { needsClaim, canClaim, canReturnToBot, botHandling, heldByTeammate };
}
