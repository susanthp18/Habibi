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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  Dispute,
  DisputeStatus,
  DisputeType,
  Evidence,
  ResolutionCode,
} from "@/api/types/disputes";
import type { QueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "./config";
import { humanNames, resolveActor, type Staff } from "./staff";
import { useRef } from "react";
import { toast } from "sonner";
import { idempotencyKey } from "@/lib/utils";

export const UNASSIGNED = "Unassigned";

export function disputeAssigneeOptions(staff: Staff[], existing: string[]): string[] {
  return humanNames(staff);
  return Array.from(new Set(existing)).sort();
}

export type CreateDisputeInput = {
  customerId: string;
  accountId?: string;
  type: DisputeType;
  amount: number;
  notes?: string;
};

export async function fetchDisputes(): Promise<Dispute[]> {
  // The SLA fields are the server's to compute; mock recomputes them on every
  // fetch (as the server would) rather than freezing them into the seed row.
  return apiGet<Dispute[]>("/disputes");
}

/** The one dispute writer: the desk and the 360 both post through here. */
export async function createDispute(
  input: CreateDisputeInput,
  idempotencyKey: string,
): Promise<{ id: string }> {
  const created = await apiPost<{ id: string }>(
    "/disputes",
    {
      customerId: input.customerId,
      accountId: input.accountId,
      type: input.type,
      amount: input.amount,
      transcriptSnippet: input.notes?.trim() || undefined,
    },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
  return { id: created.id };
}

export function useDisputes() {
  return useQuery({ queryKey: ["disputes"], queryFn: fetchDisputes, staleTime: 15_000 });
}

export async function moveDispute(d: Dispute, status: DisputeStatus): Promise<void> {
  await apiPatch(`/disputes/${d.id}`, { status });
}

export async function assignDispute(d: Dispute, assignee: string): Promise<void> {
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
  await apiPatch(`/disputes/${d.id}`, {
    status: "resolved",
    resolutionCode: code,
    resolutionNotes: notes,
  });
}

export async function rejectDispute(d: Dispute, notes: string): Promise<void> {
  await apiPatch(`/disputes/${d.id}`, {
    status: "rejected",
    resolutionCode: "invalid_no_action",
    resolutionNotes: notes,
  });
}

// ---------- mutations ----------

function invalidateDisputeReads(qc: QueryClient, customerId?: string) {
  void qc.invalidateQueries({ queryKey: ["disputes"] });
  void qc.invalidateQueries({ queryKey: ["customers"] });
  if (customerId) {
    void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    void qc.invalidateQueries({ queryKey: ["customer-insights", customerId] });
  }
}

/** One key per intent: a retried submit lands once; a success mints the next. */
export function useCreateDispute() {
  const qc = useQueryClient();
  const key = useRef(idempotencyKey("dispute"));
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (input: CreateDisputeInput) => createDispute(input, key.current),
    onSuccess: (_r, input) => {
      key.current = idempotencyKey("dispute");
      invalidateDisputeReads(qc, input.customerId);
      toast.success("Dispute filed");
    },
  });
}

export function useMoveDispute(statusLabel: (status: DisputeStatus) => string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { d: Dispute; status: DisputeStatus }) => moveDispute(v.d, v.status),
    onSuccess: (_r, v) => {
      invalidateDisputeReads(qc, v.d.customerId);
      toast.success(`${v.d.customerName} → ${statusLabel(v.status)}`);
    },
  });
}

export function useAssignDispute() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { d: Dispute; assignee: string }) => assignDispute(v.d, v.assignee),
    onSuccess: (_r, v) => {
      invalidateDisputeReads(qc, v.d.customerId);
      toast.success(`Assigned to ${v.assignee} · ${v.d.id}`);
    },
  });
}
