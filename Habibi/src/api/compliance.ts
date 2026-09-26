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
  return useQuery({ queryKey: ["violations"], queryFn: fetchViolations });
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

// -----------------------------------------------------------------------------
// Statutory rule sets — maker-checker publication.
//   GET  /compliance/policy-rules              → every set with its rules
//   POST /compliance/policy-rules/{id}/submit  → maker (policy.publish)
//   POST /compliance/policy-rules/{id}/approve → a *different* checker (policy.approve)
//   POST /compliance/policy-rules/{id}/reject  → back to the maker
// The API existed with no screen, so seeded sets sat as drafts and the contact
// gate ran on module constants with no policy_version stamped.
// -----------------------------------------------------------------------------

export type PolicyRuleSetState = "draft" | "pending_approval" | "published" | "rejected";

export type PolicyRuleSet = {
  id: string;
  scope: string;
  version: number;
  label: string | null;
  effective_from: string | null;
  effective_to: string | null;
  notes?: string | null;
  publication_state?: PolicyRuleSetState | null;
  published_by_user_id?: string | null;
  /** This viewer may break-glass approve their own pending set. */
  selfApprovable?: boolean;
  /** Why four eyes were waived, when the submitter published it. */
  self_approval_reason?: string | null;
  approved_by_user_id?: string | null;
  rules: Array<{
    kind: string;
    channel: string | null;
    params: Record<string, unknown>;
    citation: string | null;
  }>;
};

export function usePolicyRuleSets() {
  return useQuery({
    queryKey: ["policy-rule-sets"],
    queryFn: () => apiGet<PolicyRuleSet[]>("/compliance/policy-rules"),
  });
}

/** Server refusals, in the words an approver needs. */
const POLICY_ERRORS: Record<string, string> = {
  maker_checker_required: "The person who submitted a rule set cannot approve it.",
  production_publication_disabled:
    "Publication is switched off on this server (POLICY_PRODUCTION_PUBLICATION).",
  not_pending_approval: "This rule set is no longer awaiting approval — refresh.",
  not_a_draft: "Only a draft or a rejected set can be submitted.",
  changed_rules_mismatch: "The rules changed after submission; submit it again.",
  platform_write_required:
    "Statutory rules bind every tenant; submitting or approving them needs the platform-write permission.",
  row_security_refused: "The database refused this change for your tenant.",
  self_approval_not_permitted:
    "Only the operators named on the server may approve their own submission.",
  self_approval_reason_too_short: "Say why four eyes are being waived, in at least 20 characters.",
  policy_rule_set_not_writable: "This rule set could not be changed from your account.",
};

export function policyErrorMessage(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err);
  const hit = Object.keys(POLICY_ERRORS).find((k) => text.includes(k));
  return (hit && POLICY_ERRORS[hit]) || text;
}

export function usePolicyRuleSetAction() {
  const qc = useQueryClient();
  return useMutation({
    // onError below turns the server's refusal code into words.
    meta: { errors: "caller" },
    mutationFn: ({
      id,
      action,
      selfApprovalReason,
    }: {
      id: string;
      action: "submit" | "approve" | "reject";
      /** Break-glass only: the maker approving their own set says why. */
      selfApprovalReason?: string;
    }) =>
      apiPost<{ id: string; state: PolicyRuleSetState }>(
        `/compliance/policy-rules/${encodeURIComponent(id)}/${action}`,
        selfApprovalReason ? { selfApprovalReason } : {},
      ),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: ["policy-rule-sets"] });
      toast.success(`${out.id} is ${out.state.replace("_", " ")}`);
    },
    onError: (err) => toast.error(policyErrorMessage(err)),
  });
}
