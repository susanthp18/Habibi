// -----------------------------------------------------------------------------
// Callback & Scheduling Manager — data access seam.
//   fetchCallbacks() → calendar/list feed  (GET /callbacks)
//   create / assign / reschedule / complete / remind → Phase 3A writes
//
// Mock branch preserves the in-memory seed mutators exactly. Live branch maps
// to POST/PATCH endpoints; the screen shape is richer than the write response,
// so callers invalidate + refetch. Assignees/queues resolve through /staff and
// /teams (never hardcoded maps).
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  Callback,
  CbChannel,
  CbDisposition,
  CbPriority,
  CreateInput,
} from "@/api/types/callbacks";
import { CURRENT_QUEUE } from "@/lib/callbacks";
import type { Customer } from "@/api/types/customer360";
import { apiGet, apiPatch, apiPost } from "./config";
import { UNASSIGNED, humanNames, resolveActor, type Staff } from "./staff";
import { resolveTeam, teamNames, type Team } from "./teams";
import { toast } from "sonner";

/**
 * Picker roster. An empty /staff roster falls back to names already on the
 * rows, never a blank dropdown.
 */
export function callbackAssigneeOptions(staff: Staff[], existing: string[]): string[] {
  const humans = humanNames(staff);
  if (humans.length) return [UNASSIGNED, ...humans];
  const fromRows = [...new Set(existing.filter((name) => name && name !== UNASSIGNED))].sort();
  return [UNASSIGNED, ...fromRows];
}

export function callbackQueueOptions(teams: Team[]): string[] {
  return teamNames(teams);
}

export function defaultCallbackQueue(queues: string[]): string {
  if (queues.includes("Retail Collections")) return "Retail Collections";
  return queues[0] ?? CURRENT_QUEUE;
}

export type CallbackSheetCustomer = {
  id: string;
  name: string;
  accountId: string;
  preferredWindow: string;
  customerDnd: boolean;
  timezone: string;
};

export function callbackSheetCustomers(customers: Customer[]): CallbackSheetCustomer[] {
  return customers.map((c) => ({
    id: c.id,
    name: c.name,
    accountId: c.accountId,
    preferredWindow: c.contact.preferredWindow,
    customerDnd: c.contact.dnd,
    timezone: c.contact.timezone,
  }));
}

export async function fetchCallbacks(): Promise<Callback[]> {
  return apiGet<Callback[]>("/callbacks");
}

export function useCallbacks() {
  return useQuery({ queryKey: ["callbacks"], queryFn: fetchCallbacks });
}

export async function createCallback(input: CreateInput): Promise<{ id: string }> {
  let assigneeUserId: string | null = null;
  if (input.assignee && input.assignee !== UNASSIGNED) {
    const actor = await resolveActor(input.assignee);
    if (actor.kind !== "human") {
      throw new Error(`${input.assignee} is a bot — callbacks are assigned to people`);
    }
    assigneeUserId = actor.id;
  }
  const team = await resolveTeam(input.queue);
  const notes = input.notes?.trim();
  const created = await apiPost<{ id: string }>("/callbacks", {
    customerId: input.customerId,
    reason: input.reason,
    scheduledAt: input.scheduledAt,
    windowMins: input.windowMins,
    priority: input.priority,
    assigneeUserId,
    teamId: team.id,
    transcriptSnippet: notes ? `"${notes}"` : undefined,
  });

  // Queue the chosen reminder channels as first-class child rows.
  for (const channel of input.reminderChannels) {
    await apiPost(`/callbacks/${created.id}/reminders`, {
      channel,
      scheduledAt: input.scheduledAt,
      status: "queued",
    });
  }
  return created;
}

export async function assignCallback(cb: Callback, assignee: string): Promise<void> {
  if (assignee === UNASSIGNED) {
    await apiPatch(`/callbacks/${cb.id}`, { assigneeUserId: null });
    return;
  }
  const actor = await resolveActor(assignee);
  if (actor.kind !== "human") {
    throw new Error(`${assignee} is a bot — callbacks are assigned to people`);
  }
  await apiPatch(`/callbacks/${cb.id}`, { assigneeUserId: actor.id });
}

export async function reassignQueue(cb: Callback, queue: string): Promise<void> {
  const team = await resolveTeam(queue);
  await apiPatch(`/callbacks/${cb.id}`, { teamId: team.id });
}

export async function setPriority(cb: Callback, priority: CbPriority): Promise<void> {
  await apiPatch(`/callbacks/${cb.id}`, { priority });
}

export async function rescheduleCallback(cb: Callback, newISO: string): Promise<void> {
  await apiPatch(`/callbacks/${cb.id}`, { scheduledAt: newISO, status: "scheduled" });
}

export async function cancelCallback(cb: Callback, _reason: string): Promise<void> {
  await apiPatch(`/callbacks/${cb.id}`, { status: "cancelled" });
}

export async function markMissed(cb: Callback): Promise<void> {
  await apiPatch(`/callbacks/${cb.id}`, { status: "missed" });
}

/**
 * Mark the callback in progress. This does **not** place a call: the agent
 * dials from their own phone and captures the outcome here. The buttons that
 * call it say "Begin callback" for that reason -- "Start call" promised a dial
 * the product never made.
 */
export async function startCall(cb: Callback): Promise<void> {
  await apiPatch(`/callbacks/${cb.id}`, { status: "in_progress" });
}

export async function markCompleted(
  cb: Callback,
  disposition: CbDisposition,
  notes: string,
): Promise<void> {
  await apiPatch(`/callbacks/${cb.id}`, {
    status: "completed",
    disposition,
    outcomeNotes: notes,
  });
}

export async function sendReminder(cb: Callback, channel: CbChannel): Promise<void> {
  await apiPost(`/callbacks/${cb.id}/reminders`, {
    channel,
    scheduledAt: new Date().toISOString(),
    status: "sent",
  });
}

/** Bump past-window scheduled/reminded callbacks to missed. Live: real PATCHes. */
export async function autoMarkMissed(list: Callback[]): Promise<number> {
  const now = Date.now();
  const overdue = list.filter((c) => {
    if (c.status !== "scheduled" && c.status !== "reminded") return false;
    const end = new Date(c.scheduledAt).getTime() + c.windowMins * 60_000;
    return end < now;
  });
  for (const c of overdue) {
    await markMissed(c);
  }
  return overdue.length;
}

// ---------- mutations ----------
//
// Each takes the row rather than an id: the screen has it, and the write
// needs the customer on it. `callbacks` is the one read they move.

export function useRescheduleCallback() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { cb: Callback; iso: string }) => rescheduleCallback(v.cb, v.iso),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["callbacks"] });
      toast.success("Rescheduled");
    },
  });
}

export function useStartCallback() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (cb: Callback) => startCall(cb),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["callbacks"] });
      toast("Callback in progress — dial from your phone");
    },
  });
}

export function useSendCallbackReminder() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { cb: Callback; channel: CbChannel }) => sendReminder(v.cb, v.channel),
    onSuccess: (_r, v) => {
      void qc.invalidateQueries({ queryKey: ["callbacks"] });
      toast.success(`Reminder sent · ${v.channel === "whatsapp" ? "WhatsApp" : v.channel}`);
    },
  });
}

export function useCancelCallback() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { cb: Callback; reason: string }) => cancelCallback(v.cb, v.reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["callbacks"] });
      toast("Callback cancelled");
    },
  });
}
