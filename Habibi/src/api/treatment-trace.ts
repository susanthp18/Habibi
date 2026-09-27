// -----------------------------------------------------------------------------
// Decision intelligence — one decision end to end, the log, health, learning.
//
//   GET  /treatment/decisions               → the log (format=csv for export)
//   GET  /treatment/decisions/{id}          → one decision, end to end
//   GET  /treatment/current                 → the account's next best action
//   POST /treatment/decide                  → ask now; recorded, never enacted
//   GET  /treatment/health                  → every stage's last run, feeds
//   GET  /treatment/learned                 → assumptions vs learned rates
//   POST /treatment/decisions/{id}/feedback → a person corrects the record
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiGetBlob, apiPost } from "./config";

export type Evidence = {
  source: "prior" | "learned" | "history" | "delivery" | (string & {});
  value: number;
  prior?: number;
  successes?: number;
  trials?: number;
  windowDays?: number;
};

export type TraceOption = {
  action: string;
  label: string;
  chosen: boolean;
  status: "scored" | "blocked" | "not_considered";
  rank?: number;
  expectedValue?: number | null;
  pReach?: number | null;
  pResolve?: number | null;
  cost?: number | null;
  at?: string | null;
  explanation?: string | null;
  timingRationale?: string | null;
  evidence?: { reach?: Evidence; resolve?: Evidence };
  pickProbability?: number | null;
  reasonCodes?: string[];
  code?: string;
  reason?: string;
};

export type TraceCall = {
  id: string;
  state: string;
  placed_at: string | null;
  interaction_id: string | null;
  disposition: string | null;
  duration_sec: number | null;
  connection: string | null;
  business: string | null;
  summary: string | null;
};

export type DecisionTrace = {
  id: string;
  family: string;
  customerId: string;
  customerName: string | null;
  accountId: string | null;
  createdAt: string;
  mode: string;
  variant: string | null;
  whyNow: {
    trigger: string;
    triggerRef: string | null;
    facts: Array<{ label: string; key: string; value: unknown }>;
    dataFreshness: Array<{ feed: string; name?: string; lastReceivedAt: string | null; lagHours: number | null }>;
  };
  options: TraceOption[];
  choice: {
    action: string;
    label: string;
    channel: string | null;
    scheduledAt: string | null;
    expectedValue: number | null;
    held: boolean;
    holdReason: string | null;
    holdReasonText: string | null;
    how: string;
    howText: string;
    pickProbability: number | null;
    beat: { action: string; label: string; byInr: number } | null;
    rationale: string | null;
  };
  versions: Record<string, string | number | null>;
  happened: {
    enacted: boolean;
    enactedAt: string | null;
    enactedBy: string | null;
    enactedRef: string | null;
    cancelReason: string | null;
    calls: TraceCall[];
    messages: Array<{ id: string; status: string; template_name: string | null; created_at: string }>;
    promisesSince: Array<{
      id: string;
      amount: number;
      promised_at: string;
      status: string;
      interaction_id: string | null;
    }>;
    paymentsSince: Array<{ id: string; amount: number; posted_at: string }>;
    label: {
      outcome: string | null;
      outcomeAt: string | null;
      reach: string | null;
      cure: string | null;
      matureAt: string | null;
      definition: string | null;
    };
  };
  feedback: Array<{
    verdict: string;
    reason_code: string | null;
    corrected_outcome: string | null;
    note_redacted: string | null;
    actor_role: string | null;
    created_at: string;
  }>;
};

export type DecisionLogRow = {
  id: string;
  created_at: string;
  customer_id: string;
  customer_name: string;
  account_id: string | null;
  trigger_kind: string;
  trigger_ref: string | null;
  mode: string;
  variant: string | null;
  chosen_action: string | null;
  chosen_channel: string | null;
  scheduled_at: string | null;
  expected_value: number | null;
  suppression_reason: string | null;
  holdReasonText: string | null;
  explore_kind: string | null;
  enacted: boolean;
  enacted_at: string | null;
  outcome: string | null;
  rationale: string | null;
};

export type DecisionLogQuery = {
  customerId?: string | null;
  action?: string | null;
  outcome?: string | null;
  held?: boolean | null;
  limit?: number;
  offset?: number;
};

function logParams(q: DecisionLogQuery): URLSearchParams {
  const p = new URLSearchParams();
  if (q.customerId) p.set("customerId", q.customerId);
  if (q.action) p.set("action", q.action);
  if (q.outcome) p.set("outcome", q.outcome);
  if (q.held != null) p.set("held", String(q.held));
  if (q.limit != null) p.set("limit", String(q.limit));
  if (q.offset != null) p.set("offset", String(q.offset));
  return p;
}

export type StageHealth = {
  key: string;
  label: string;
  does: string;
  lastAt: string | null;
  status: "ok" | "late" | "never";
  lastResult?: {
    status: string;
    result: Record<string, unknown>;
    error: string | null;
    updated_at: string;
  } | null;
};

export type TreatmentHealth = {
  mode: string;
  enactSwitchOn: boolean;
  labelsOn: boolean;
  stages: StageHealth[];
  feeds: Array<{ feed: string; name?: string; lastReceivedAt: string | null; lagHours: number | null }>;
  blockers: Array<{ code: string; text: string; borrowers: number }>;
};

const TRIGGERS: Record<string, string> = {
  dpd_tick: "Daily review",
  bounce: "EMI bounced",
  broken_ptp: "Promise broken",
  pre_due: "Instalment due soon",
  inbound: "Customer got in touch",
  manual: "Asked on screen",
  no_contact: "No contact in a while",
  wrap_up: "Call just ended",
};

/** Why a decision was made, in words. */
export function triggerLabel(kind: string | null | undefined): string {
  return (kind && TRIGGERS[kind]) || (kind ?? "—").replace(/_/g, " ");
}

const GROUPS: Record<string, string> = {
  control: "Standard (engine decides)",
  null_treatment: "Comparison group (policy only)",
};

/** The randomised group a borrower is in, in words. */
export function groupLabel(variant: string | null | undefined): string {
  return variant ? (GROUPS[variant] ?? variant.replace(/_/g, " ")) : "—";
}

export type LearnedRate = { metric: "reach" | "resolve"; key: string; label: string } & Evidence;

export function useDecisionLog(q: DecisionLogQuery) {
  return useQuery({
    queryKey: ["treatment-decisions", q],
    queryFn: () => apiGet<DecisionLogRow[]>(`/treatment/decisions?${logParams(q).toString()}`),
    staleTime: 30_000,
  });
}

/** The CSV export for an auditor: the same filters, up to 5,000 rows. */
export async function downloadDecisionLog(q: DecisionLogQuery): Promise<void> {
  const p = logParams({ ...q, limit: 5000, offset: 0 });
  p.set("format", "csv");
  const { blob } = await apiGetBlob(`/treatment/decisions?${p.toString()}`);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "decisions.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function useDecisionTrace(decisionId: string | null | undefined) {
  return useQuery({
    queryKey: ["treatment-trace", decisionId],
    queryFn: () => apiGet<DecisionTrace>(`/treatment/decisions/${encodeURIComponent(decisionId!)}`),
    enabled: Boolean(decisionId),
  });
}

export function useCurrentDecision(customerId: string | null | undefined, accountId?: string | null) {
  return useQuery({
    queryKey: ["treatment-current", customerId, accountId ?? null],
    queryFn: () => {
      const p = new URLSearchParams({ customerId: customerId! });
      if (accountId) p.set("accountId", accountId);
      return apiGet<{ decision: DecisionTrace | null }>(`/treatment/current?${p.toString()}`);
    },
    enabled: Boolean(customerId),
  });
}

/** Ask the engine now. Recorded in shadow mode: traceable, never carried out. */
export function useDecideNow() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: { customerId: string; accountId?: string | null }) =>
      apiPost<DecisionTrace>("/treatment/decide", {
        customerId: input.customerId,
        ...(input.accountId ? { accountId: input.accountId } : {}),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["treatment-current"] });
      void qc.invalidateQueries({ queryKey: ["treatment-decisions"] });
      void qc.invalidateQueries({ queryKey: ["customer-insights"] });
    },
  });
}

export function useTreatmentHealth(days = 1) {
  return useQuery({
    queryKey: ["treatment-health", days],
    queryFn: () => apiGet<TreatmentHealth>(`/treatment/health?days=${days}`),
    staleTime: 60_000,
  });
}

export function useLearnedRates() {
  return useQuery({
    queryKey: ["treatment-learned"],
    queryFn: () => apiGet<LearnedRate[]>("/treatment/learned"),
    staleTime: 5 * 60_000,
  });
}

export type DecisionFeedbackInput = {
  decisionId: string;
  verdict: "wrong_number" | "stop_contact" | "deceased" | "other";
  note?: string;
};

export function useDecisionFeedback() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: DecisionFeedbackInput) =>
      apiPost(`/treatment/decisions/${encodeURIComponent(input.decisionId)}/feedback`, {
        verdict: input.verdict,
        ...(input.note ? { note: input.note } : {}),
      }),
    onSuccess: (_d, input) => {
      void qc.invalidateQueries({ queryKey: ["treatment-trace", input.decisionId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Strategy: the engine's settings, and changes proposed and approved by two people.
// ---------------------------------------------------------------------------

export type StrategySetting = {
  key: string;
  group: string;
  label: string;
  help: string;
  value: string | number | boolean | null;
  source: "configured" | "environment" | "default";
  type: string;
  minimum: number | null;
  maximum: number | null;
  choices: string[] | null;
};

export type StrategyProposal = {
  id: string;
  changes: Record<string, unknown>;
  reason: string;
  evidence: Record<string, unknown>;
  impact: {
    estimated?: boolean;
    note?: string;
    days?: number;
    decisions?: number;
    changed?: number;
    moves?: Array<{ move: string; count: number }>;
  };
  proposed_by: string;
  proposed_via: "person" | "advisor" | (string & {});
  status: "pending" | "approved" | "rejected" | "withdrawn";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
};

export function useStrategySettings() {
  return useQuery({
    queryKey: ["treatment-strategy"],
    queryFn: () => apiGet<StrategySetting[]>("/treatment/strategy"),
  });
}

export function useStrategyProposals() {
  return useQuery({
    queryKey: ["treatment-strategy-proposals"],
    queryFn: () => apiGet<StrategyProposal[]>("/treatment/strategy/proposals"),
  });
}

export function useProposeStrategy() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: { changes: Record<string, unknown>; reason: string }) =>
      apiPost<StrategyProposal>("/treatment/strategy/proposals", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["treatment-strategy-proposals"] }),
  });
}

export function useDecideStrategy() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: { id: string; approve: boolean; note?: string }) =>
      apiPost<StrategyProposal>(
        `/treatment/strategy/proposals/${encodeURIComponent(input.id)}/${input.approve ? "approve" : "reject"}`,
        input.note ? { note: input.note } : {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["treatment-strategy-proposals"] });
      void qc.invalidateQueries({ queryKey: ["treatment-strategy"] });
      void qc.invalidateQueries({ queryKey: ["treatment-health"] });
    },
  });
}

/** A plain-language explanation written only from the stored trace. */
export function useExplainDecision() {
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (decisionId: string) =>
      apiPost<{ text: string; source: "llm" | "rule" }>(
        `/treatment/decisions/${encodeURIComponent(decisionId)}/explain`,
        {},
      ),
  });
}
