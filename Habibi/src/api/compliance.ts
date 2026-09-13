// -----------------------------------------------------------------------------
// Compliance Risk — data access seam.
//   fetchViolations() → feed list  (GET /violations)
//   assign / acknowledge / resolve / add note → Phase 3A writes (hardened in 3B)
//
// Writes map to PATCH + POST /notes; the screen shape is richer than the write
// response, so callers invalidate + refetch. Assignees resolve through /staff;
// the note author is the acting user from GET /me.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Violation, ViolationStatus } from "@/api/types/compliance";
import { apiGet, apiPatch, apiPost } from "./config";
import { currentActor } from "./me";
import { humanNames, resolveActor, type Staff } from "./staff";
import { toast } from "sonner";

export function violationAssigneeOptions(staff: Staff[]): string[] {
  return humanNames(staff);
}

export async function exportPolicyBundle(fmt: "opa" | "cedar"): Promise<{
  format: string;
  text: string;
}> {
  return apiGet<{ format: string; text: string }>(`/compliance/policy-export?fmt=${fmt}`);
}

export async function fetchViolations(): Promise<Violation[]> {
  return apiGet<Violation[]>("/violations");
}

export function useViolations() {
  return useQuery({ queryKey: ["violations"], queryFn: fetchViolations, staleTime: 15_000 });
}

async function postNote(id: string, note: string): Promise<void> {
  const text = note.trim();
  if (!text) return;
  await apiPost(`/violations/${id}/notes`, { text });
}

/** PATCH status then POST note — rollback status if note fails (no combined backend endpoint). */
async function patchStatusThenNote(
  v: Violation,
  patch: { status: ViolationStatus; assigneeUserId?: string },
  note: string,
): Promise<void> {
  const prevStatus = v.status;
  // assignViolation sends assigneeUserId alongside status, so the rollback has
  // to restore both — reverting status alone left the violation reassigned to
  // whoever the failed call named. The client model carries the assignee's
  // display name, so resolve it back to an id (and clear the field outright
  // when there was no previous assignee).
  const prevAssignee = v.assignee;
  await apiPatch(`/violations/${v.id}`, patch);
  try {
    await postNote(v.id, note);
  } catch (noteErr) {
    const detail = noteErr instanceof Error ? noteErr.message : "note failed";
    try {
      const rollback: { status: ViolationStatus; assigneeUserId?: string | null } = {
        status: prevStatus,
      };
      if (patch.assigneeUserId !== undefined) {
        rollback.assigneeUserId = prevAssignee ? (await resolveActor(prevAssignee)).id : null;
      }
      await apiPatch(`/violations/${v.id}`, rollback);
    } catch {
      throw new Error(
        `Status updated but note failed (${detail}). Could not revert status — refresh the list.`,
      );
    }
    throw new Error(`Note failed after status update; reverted to "${prevStatus}". ${detail}`);
  }
}

export async function assignViolation(
  v: Violation,
  assignee: string,
  note = "Assigned for review.",
): Promise<void> {
  const actor = await resolveActor(assignee);
  if (actor.kind !== "human") {
    throw new Error(`${assignee} is a bot — compliance review is assigned to people`);
  }
  await patchStatusThenNote(
    v,
    { status: "in_review" satisfies ViolationStatus, assigneeUserId: actor.id },
    note,
  );
}

export async function acknowledgeViolation(v: Violation, note = "Acknowledged."): Promise<void> {
  await patchStatusThenNote(v, { status: "acknowledged" satisfies ViolationStatus }, note);
}

export async function resolveViolation(v: Violation, note: string): Promise<void> {
  const text = note.trim();
  if (!text) throw new Error("A resolution note is required");
  await patchStatusThenNote(v, { status: "resolved" satisfies ViolationStatus }, text);
}

export async function addViolationNote(v: Violation, note: string): Promise<void> {
  await postNote(v.id, note);
}

export type { Violation, ViolationStatus };

// -----------------------------------------------------------------------------
// Detector coverage — GET /compliance/rule-coverage.
//
// `groupByRule` can only show rules that have already produced a violation, so
// a rule nobody is checking and a rule with a spotless record rendered the same
// way: absent. Fifteen of the sixteen seeded rules were in the first category.
// This endpoint reports every catalog rule with a three-way state, so "clean"
// is only ever claimed for a rule that is actually being looked for.
// -----------------------------------------------------------------------------

export type RuleState = "clean" | "breached" | "unverified" | "disabled";

export interface RuleCoverageRow {
  ruleId: string;
  code: string;
  label: string;
  severity: string;
  enabled: boolean;
  hasDetector: boolean;
  state: RuleState;
  total: number;
  open: number;
  lastSeen: string | null;
}

export interface RuleCoverage {
  rules: RuleCoverageRow[];
  interactionsEvaluated: number;
  rulesVersion: number;
  detectorsRegistered: number;
}

export function useRuleCoverage() {
  return useQuery({
    queryKey: ["compliance-rule-coverage"],
    queryFn: async (): Promise<RuleCoverage> => {
      return apiGet<RuleCoverage>("/compliance/rule-coverage");
    },
    staleTime: 60_000,
  });
}

// ---------- mutations ----------

export function useAssignViolation() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { item: Violation; assignee: string; note: string }) =>
      assignViolation(v.item, v.assignee, v.note),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["violations"] });
      toast.success("Assigned for review", { description: `${v.item.id} → ${v.assignee}` });
    },
  });
}

export function useAcknowledgeViolation() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { item: Violation; note: string }) => acknowledgeViolation(v.item, v.note),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["violations"] });
      toast.success("Acknowledged", { description: v.item.id });
    },
  });
}

export function useResolveViolation() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { item: Violation; note: string }) => resolveViolation(v.item, v.note),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["violations"] });
      toast.success("Marked resolved", { description: v.item.id });
    },
  });
}
