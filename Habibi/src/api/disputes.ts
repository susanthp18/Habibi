// -----------------------------------------------------------------------------
// Disputes & Exceptions Queue — data access seam.
//   fetchDisputes()  → kanban list   (GET /disputes)
//   move / assign / resolve / reject / attachEvidence → Phase 3A writes
//
// Mock branch preserves the in-memory seed mutators exactly. Live branch maps
// to PATCH/POST endpoints; the screen shape is richer than the 360 write
// response, so callers invalidate + refetch rather than trusting the body.
//
// Assignment resolves names through the real /staff roster (see api/staff.ts)
// rather than a hardcoded map, so it can't drift from the DB.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  addNote as addSeedNote,
  assignDispute as assignSeedDispute,
  attachEvidence as attachSeedEvidence,
  createDispute as createSeedDispute,
  disputes as seedDisputes,
  moveDispute as moveSeedDispute,
  rejectDispute as rejectSeedDispute,
  resolveDispute as resolveSeedDispute,
  withMockSla,
  type Dispute,
  type DisputeStatus,
  type DisputeType,
  type Evidence,
  type ResolutionCode,
} from "@/data/disputes-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { resolveActor } from "./staff";

export const UNASSIGNED = "Unassigned";

export type CreateDisputeInput = {
  customerId: string;
  /** Display name — required for mock seed rows; live API resolves it server-side. */
  customerName?: string;
  accountId: string;
  type: DisputeType;
  amount: number;
  notes?: string;
};

export async function fetchDisputes(): Promise<Dispute[]> {
  // The SLA fields are the server's to compute; mock recomputes them on every
  // fetch (as the server would) rather than freezing them into the seed row.
  if (USE_MOCK) return mockDelay(seedDisputes.map(withMockSla));
  return apiGet<Dispute[]>("/disputes");
}

/** Raise a dispute from the Disputes desk (or workspace quick action). */
export async function createDispute(input: CreateDisputeInput): Promise<{ id: string }> {
  if (USE_MOCK) {
    const d = createSeedDispute({
      ...input,
      customerName: input.customerName?.trim() || input.customerId,
    });
    await mockDelay(undefined);
    return { id: d.id };
  }
  const created = await apiPost<{ id: string }>("/disputes", {
    customerId: input.customerId,
    accountId: input.accountId,
    type: input.type,
    amount: input.amount,
    transcriptSnippet: input.notes?.trim() || undefined,
  });
  return { id: created.id };
}

export function useDisputes() {
  return useQuery({ queryKey: ["disputes"], queryFn: fetchDisputes, staleTime: 15_000 });
}

export async function moveDispute(d: Dispute, status: DisputeStatus): Promise<void> {
  if (USE_MOCK) {
    moveSeedDispute(d.id, status);
    return;
  }
  await apiPatch(`/disputes/${d.id}`, { status });
}

export async function assignDispute(d: Dispute, assignee: string): Promise<void> {
  if (USE_MOCK) {
    assignSeedDispute(d.id, assignee);
    return;
  }
  if (assignee === UNASSIGNED) {
    // Explicit null clears the column (PATCH uses exclude_unset server-side).
    await apiPatch(`/disputes/${d.id}`, { assigneeUserId: null });
    return;
  }
  const actor = await resolveActor(assignee);
  if (actor.kind !== "human") {
    throw new Error(`${assignee} is a bot — disputes are assigned to people`);
  }
  await apiPatch(`/disputes/${d.id}`, { assigneeUserId: actor.id });
}

export async function addNote(d: Dispute, note: string): Promise<void> {
  if (USE_MOCK) {
    addSeedNote(d.id, note);
    return;
  }
  await apiPost(`/disputes/${d.id}/notes`, { text: note.trim() });
}

function mimeFromFilename(name: string): string {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return "application/pdf";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".mp3")) return "audio/mpeg";
  if (lower.endsWith(".wav")) return "audio/wav";
  return "application/octet-stream";
}

export async function attachEvidence(
  d: Dispute,
  name: string,
  kind: Evidence["kind"] = "other",
): Promise<void> {
  if (USE_MOCK) {
    attachSeedEvidence(d.id, name, kind);
    return;
  }
  const filename = name.trim() || `evidence-${Date.now()}.pdf`;
  // storageRef is omitted on purpose — the server owns the storage layout
  // (and knows the tenant); clients shouldn't invent paths.
  await apiPost(`/disputes/${d.id}/evidence`, {
    filename,
    mimeType: mimeFromFilename(filename),
  });
}

export async function resolveDispute(
  d: Dispute,
  code: ResolutionCode,
  notes: string,
): Promise<void> {
  if (USE_MOCK) {
    resolveSeedDispute(d.id, code, notes);
    return;
  }
  await apiPatch(`/disputes/${d.id}`, {
    status: "resolved",
    resolutionCode: code,
    resolutionNotes: notes,
  });
}

export async function rejectDispute(d: Dispute, notes: string): Promise<void> {
  if (USE_MOCK) {
    rejectSeedDispute(d.id, notes);
    return;
  }
  await apiPatch(`/disputes/${d.id}`, {
    status: "rejected",
    resolutionCode: "invalid_no_action",
    resolutionNotes: notes,
  });
}
