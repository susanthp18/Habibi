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

import { useQuery } from "@tanstack/react-query";

import {
  assign as assignSeed,
  autoMarkMissed as autoMarkSeedMissed,
  cancel as cancelSeed,
  createCallback as createSeedCallback,
  markCompleted as markSeedCompleted,
  markMissed as markSeedMissed,
  reassignQueue as reassignSeedQueue,
  reschedule as rescheduleSeed,
  sendReminder as sendSeedReminder,
  setPriority as setSeedPriority,
  startCall as startSeedCall,
  callbacks as seedCallbacks,
  type Callback,
  type CbChannel,
  type CbDisposition,
  type CbPriority,
  type CreateInput,
} from "@/data/callbacks-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { resolveActor } from "./staff";
import { resolveTeam } from "./teams";

export const UNASSIGNED = "Unassigned";

export async function fetchCallbacks(): Promise<Callback[]> {
  if (USE_MOCK) return mockDelay(seedCallbacks);
  return apiGet<Callback[]>("/callbacks");
}

export function useCallbacks() {
  return useQuery({ queryKey: ["callbacks"], queryFn: fetchCallbacks, staleTime: 15_000 });
}

export async function createCallback(input: CreateInput): Promise<{ id: string }> {
  if (USE_MOCK) {
    const created = createSeedCallback(input);
    return { id: created.id };
  }

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
  if (USE_MOCK) {
    assignSeed(cb.id, assignee);
    return;
  }
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
  if (USE_MOCK) {
    reassignSeedQueue(cb.id, queue);
    return;
  }
  const team = await resolveTeam(queue);
  await apiPatch(`/callbacks/${cb.id}`, { teamId: team.id });
}

export async function setPriority(cb: Callback, priority: CbPriority): Promise<void> {
  if (USE_MOCK) {
    setSeedPriority(cb.id, priority);
    return;
  }
  await apiPatch(`/callbacks/${cb.id}`, { priority });
}

export async function rescheduleCallback(cb: Callback, newISO: string): Promise<void> {
  if (USE_MOCK) {
    rescheduleSeed(cb.id, newISO);
    return;
  }
  await apiPatch(`/callbacks/${cb.id}`, { scheduledAt: newISO, status: "scheduled" });
}

export async function cancelCallback(cb: Callback, _reason: string): Promise<void> {
  if (USE_MOCK) {
    cancelSeed(cb.id, _reason);
    return;
  }
  await apiPatch(`/callbacks/${cb.id}`, { status: "cancelled" });
}

export async function markMissed(cb: Callback): Promise<void> {
  if (USE_MOCK) {
    markSeedMissed(cb.id);
    return;
  }
  await apiPatch(`/callbacks/${cb.id}`, { status: "missed" });
}

export async function startCall(cb: Callback): Promise<void> {
  if (USE_MOCK) {
    startSeedCall(cb.id);
    return;
  }
  await apiPatch(`/callbacks/${cb.id}`, { status: "in_progress" });
}

export async function markCompleted(
  cb: Callback,
  disposition: CbDisposition,
  notes: string,
): Promise<void> {
  if (USE_MOCK) {
    markSeedCompleted(cb.id, disposition, notes);
    return;
  }
  await apiPatch(`/callbacks/${cb.id}`, {
    status: "completed",
    disposition,
    outcomeNotes: notes,
  });
}

export async function sendReminder(cb: Callback, channel: CbChannel): Promise<void> {
  if (USE_MOCK) {
    sendSeedReminder(cb.id, channel);
    return;
  }
  await apiPost(`/callbacks/${cb.id}/reminders`, {
    channel,
    scheduledAt: new Date().toISOString(),
    status: "sent",
  });
}

/** Bump past-window scheduled/reminded callbacks to missed. Live: real PATCHes. */
export async function autoMarkMissed(list: Callback[]): Promise<number> {
  if (USE_MOCK) return autoMarkSeedMissed();
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
