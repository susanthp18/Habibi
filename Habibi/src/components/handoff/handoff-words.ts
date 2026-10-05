import { toast } from "sonner";
import { ApiError } from "@/api/config";

const SERVER_WORDS: Record<string, string> = {
  handoff_already_claimed: "Someone else claimed this case a moment ago.",
  handoff_already_completed: "This case has already been wrapped up.",
  handoff_not_found: "This case no longer exists.",
  handoff_not_assigned: "This case isn't yours. Claim it first, or ask a supervisor to take it.",
  identity_locked: "Identity is already verified on this call and can't be undone.",
  unknown_disposition: "Pick an outcome.",
  promise_already_open:
    "This loan already has an open promise. Revise that one on the Promises page instead.",
  handoff_closed: "This case is already wrapped up; nothing more can be saved on it.",
  handoff_owner_changed:
    "Someone else took this case a moment ago. Check who holds it now before taking it over.",
  reassign_requires_supervisor: "Only a supervisor can take over a colleague's case.",
  promise_date_in_past: "The promise date has passed. Choose today or a later date.",
  callback_in_past: "That callback time has passed. Choose a later time.",
  records_need_collections_write:
    "Your role can't file promises, disputes or callbacks. Choose an outcome that needs only a note.",
  disclosure_said_by_bot: "The bot said this on the call; its evidence can't be changed here.",
  disclosure_attested_by_other:
    "A colleague attested this before you held the case; their attestation stays theirs.",
};

/** Lost access, not a blip: the case is someone else's now, or gone. */
export function isAccessLoss(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}

const NEEDS: Record<string, string> = {
  promise: "This outcome needs the promise: an amount and a date.",
  callback: "This outcome needs the callback's time.",
  dispute: "This outcome needs the dispute's type.",
  notes: "This outcome needs a note saying what happened.",
};

/** A Hub write's failure as one sentence: never the request line or a permission id. */
export function handoffErrorWords(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : "The request failed.";
  }
  const [code = "", arg = ""] = error.detail.split(":", 2).map((s) => s.trim());
  if (code === "disposition_needs" && arg && NEEDS[arg]) return NEEDS[arg];
  if (SERVER_WORDS[code]) return SERVER_WORDS[code];
  if (error.status === 403) return "You don't have permission to do that.";
  if (error.status === 429) return "Too many requests — try again in a moment.";
  if (error.status >= 500) return "The server couldn't complete that. Try again in a moment.";
  return error.detail || "The request failed.";
}

/** Copy text for the agent to say or send. Nothing here speaks or writes a turn. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied");
    return true;
  } catch {
    toast.error("Couldn't copy — select the text instead");
    return false;
  }
}

/** How long a caller has been waiting, in the queue's words. */
export function waitWords(sec: number) {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m >= 24 * 60) {
    const d = Math.floor(m / (24 * 60));
    const h = Math.floor((m % (24 * 60)) / 60);
    return h ? `${d}d ${h}h` : `${d}d`;
  }
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  }
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}
