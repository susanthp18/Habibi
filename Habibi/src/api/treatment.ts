// -----------------------------------------------------------------------------
// Decision intelligence — data access seam for the nine /treatment/* endpoints.
//
// The treatment engine has been writing a shadow corpus since it shipped and
// nothing rendered it, so "is it safe to switch on?" was only answerable by
// hand. These are the nine reads/writes that back the operator console:
//
//   GET  /treatment/next                    → what the engine would do, now
//   GET  /treatment/insights                → coverage + suppression mix
//   GET  /treatment/metrics                 → S17 scoreboard (causal, cost)
//   GET  /treatment/model-health            → drift + calibration
//   GET  /treatment/models                  → champion/challenger ledger
//   GET  /treatment/holds                   → active + released holds
//   POST /treatment/holds                   → place a hold
//   POST /treatment/holds/{id}/release      → lift one
//   GET  /treatment/cases                   → the ladder, one row per case
//
// Every numeric field the backend can leave undetermined is `number | null`.
// Null means the denominator was zero or the arm was too thin — which is NOT
// the same fact as 0, and rendering both as "0%" is exactly how a dead engine
// looks like a working one. The UI must print "—" for null and never coerce.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "./config";

// ---------------------------------------------------------------------------
// GET /treatment/next
// ---------------------------------------------------------------------------

/** One scored action the engine considered but did not choose. */
export type TreatmentCandidate = {
  action: string;
  channel: string | null;
  at: string | null;
  expectedValue: number;
  pReach: number;
  pResolve: number;
  cost: number;
  reasonCodes: string[];
  components: Record<string, number>;
};

export type TreatmentNext = {
  action: string;
  actionLabel: string;
  channel: string | null;
  at: string | null;
  expectedValueInr: number;
  suppressed: boolean;
  reason: string | null;
  reasonText: string | null;
  rationale: string;
  decisionId: string | null;
  propensity: number | null;
  policyVersion: number;
  /** off | shadow | live. Outside live the engine decides and enacts nothing. */
  mode: string;
  variant: string | null;
  latencyMs: number;
  alternatives: TreatmentCandidate[];
  /** action → why it was vetoed before scoring. */
  excluded: Record<string, string>;
  /** Absent for a suppressed or `wait` decision — a contract authorises action. */
  contract?: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// GET /treatment/insights
// ---------------------------------------------------------------------------

export type TreatmentInsights = {
  windowDays: number;
  decisions: number;
  actionable: number;
  coverage: number;
  enacted: number;
  customers: number;
  expectedValueInr: number;
  avgLatencyMs: number;
  suppression: Array<{ reason: string; count: number }>;
  byAction: Array<{ action: string; count: number; avgExpectedValue: number }>;
  byMode: Array<{ mode: string; count: number }>;
  outcomes: Array<{ outcome: string; count: number }>;
};

// ---------------------------------------------------------------------------
// GET /treatment/model-health (also nested inside /treatment/metrics)
// ---------------------------------------------------------------------------

export type CalibrationBin = {
  bin: number;
  n: number;
  predicted: number;
  observed: number;
};

export type TreatmentModelHealth = {
  windowDays: number;
  decisions: number;
  sampleLimit: number;
  truncated: boolean;
  driftSampled: number;
  driftSampleLimit: number;
  reachCalibration: {
    n: number;
    ece: number | null;
    bins: CalibrationBin[];
    quantity: string;
  };
  upliftCalibration: {
    available: boolean;
    reason?: string;
    treatedN: number;
    controlN: number;
    predictedTau?: number | null;
    measuredAte?: number | null;
  };
  featureDrift: {
    available: boolean;
    reason?: string;
    features: Array<{ feature: string; psi: number | null; drifted?: boolean }>;
  };
  models: {
    reach: string | null;
    uplift: string | null;
    upliftSegments: number;
  };
  alerts: Array<{ metric: string; message: string } | string>;
};

// ---------------------------------------------------------------------------
// GET /treatment/metrics
// ---------------------------------------------------------------------------

export type TreatmentMetrics = {
  windowDays: number;
  causal: {
    available: boolean;
    /** Why there is no causal number. Printed verbatim — it is the finding. */
    reason?: string;
    controlN: number;
    treatedN: number;
    ate?: number | null;
    stderr?: number | null;
    significant?: boolean;
    incrementalRecoveryPerRupee?: number | null;
  };
  efficiency: {
    resolutions: number;
    contacts: number;
    voiceMinutes: number;
    voiceCalls: number;
    contactsPerResolution: number | null;
    voiceMinutesPerResolution: number | null;
    voiceMinutesPerLakhRecovered: number | null;
    recoveredInr: number;
  };
  modelHealth: TreatmentModelHealth;
  compliance: {
    attempts: number;
    allowed: number;
    denied: number;
    denialRate: number | null;
    denialsByReason: Array<{ reason: string; n: number }>;
    windowBreaches: number;
    capBreaches: number;
    worstDayTouches: number;
    dailyCap: number;
    breaches: number;
    breachTarget: number;
    breachNote: string;
    optOuts: number;
    complaints: { available: boolean; reason?: string; n?: number };
  };
  borrowerExperience: {
    cases: number;
    contactsPerCase: number | null;
    worstCaseContacts: number;
    casesOverFiveContacts: number;
    heavyCaseShare: number | null;
  };
  capacity: {
    solved: boolean;
    resources: Array<{
      resource: string;
      daysSolved: number;
      avgDualPriceInr: number;
      priceSpreadInr: number;
      stability: string;
      utilisation: number;
      nonConvergedDays: number;
    }>;
  };
};

// ---------------------------------------------------------------------------
// GET /treatment/models
// ---------------------------------------------------------------------------

export type SegmentLadderRung = {
  segment: string;
  label?: string;
  verdict: "promoted" | "rejected" | "skipped" | string;
  reason?: string;
  ate?: number;
  ateStderr?: number;
  z?: number;
  zRequired?: number;
  controlN?: number;
  treatedN?: number;
  holdoutLift?: number;
  holdoutLoglossSegment?: number;
  holdoutLoglossPopulation?: number;
};

export type TreatmentModelRecord = {
  id: string;
  target: string;
  version: string;
  status: "champion" | "challenger" | "retired" | string;
  corpus: string;
  n_samples: number;
  control_n: number;
  segments_promoted: number;
  registered_at: string;
  promoted_at: string | null;
  promoted_by: string | null;
  retired_at: string | null;
  reason: string | null;
  metrics: {
    ate?: number;
    baseRate?: number;
    holdoutN?: number;
    holdoutAuc?: number;
    controlRate?: number;
    segmentsPromoted?: number;
    segmentLadder?: SegmentLadderRung[];
  } | null;
  evaluation?: Record<string, unknown> | null;
};

/**
 * Whether the file on disk is the one a promotion produced.
 *
 * The half worth reading first: a registry that only records promotions cannot
 * tell you the artifact underneath one was swapped afterwards, and every log
 * line downstream would keep naming the promoted version.
 */
export type TreatmentServingCheck = {
  target: string;
  state: "ok" | "unregistered" | "stale" | "missing" | string;
  detail: string;
};

export type TreatmentModels = {
  history: TreatmentModelRecord[];
  serving: TreatmentServingCheck[];
};

// ---------------------------------------------------------------------------
// /treatment/holds
// ---------------------------------------------------------------------------

export const HOLD_KINDS = ["hardship", "dispute", "complaint", "bereavement", "legal"] as const;

export type HoldKind = (typeof HOLD_KINDS)[number];

export const HOLD_SOURCES = ["manual", "bot", "system", "regulator"] as const;

export type HoldSource = (typeof HOLD_SOURCES)[number];

export type TreatmentHold = {
  id: string;
  customerId: string;
  /** Present on the list read (joined); absent on the create/release response. */
  customerName?: string | null;
  accountId: string | null;
  kind: HoldKind | string;
  reason: string | null;
  source: HoldSource | string;
  interactionId: string | null;
  slaDueAt: string | null;
  startsAt: string;
  expiresAt: string | null;
  releasedAt: string | null;
  releasedReason: string | null;
  placedBy?: string | null;
  specialist?: string | null;
  active: boolean;
  createdAt: string;
};

export type TreatmentHoldInput = {
  customerId: string;
  accountId?: string | null;
  kind: HoldKind;
  reason?: string | null;
  source?: HoldSource;
  interactionId?: string | null;
  specialistUserId?: string | null;
  slaDueAt?: string | null;
  expiresAt?: string | null;
};

// ---------------------------------------------------------------------------
// GET /treatment/cases
// ---------------------------------------------------------------------------

export type TreatmentCase = {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string | null;
  trigger: string;
  triggerRef: string;
  decisions: number;
  attempts: number;
  /** Actions actually enacted, oldest first — the rungs already walked. */
  ladder: string[];
  lastAction: string | null;
  lastOutcome: string | null;
  lastSuppression: string | null;
  rationale: string | null;
  lastDecidedAt: string;
  lastAttemptAt: string | null;
};

// ---------------------------------------------------------------------------
// Fetchers — one per endpoint, each with its mock branch.
// ---------------------------------------------------------------------------

export async function fetchTreatmentNext(
  customerId: string,
  accountId?: string | null,
  trigger = "manual",
): Promise<TreatmentNext> {
  const params = new URLSearchParams({ customerId, trigger });
  if (accountId) params.set("accountId", accountId);
  return apiGet<TreatmentNext>(`/treatment/next?${params.toString()}`);
}

export async function fetchTreatmentInsights(days = 14): Promise<TreatmentInsights> {
  return apiGet<TreatmentInsights>(`/treatment/insights?days=${days}`);
}

export async function fetchTreatmentMetrics(
  days = 28,
  includeSimulated = false,
): Promise<TreatmentMetrics> {
  return apiGet<TreatmentMetrics>(
    `/treatment/metrics?days=${days}&includeSimulated=${includeSimulated}`,
  );
}

export async function fetchTreatmentModelHealth(
  days = 14,
  includeSimulated = false,
): Promise<TreatmentModelHealth> {
  return apiGet<TreatmentModelHealth>(
    `/treatment/model-health?days=${days}&includeSimulated=${includeSimulated}`,
  );
}

export async function fetchTreatmentModels(
  target?: string | null,
  limit = 50,
): Promise<TreatmentModels> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (target) params.set("target", target);
  return apiGet<TreatmentModels>(`/treatment/models?${params.toString()}`);
}

export type HoldQuery = {
  customerId?: string | null;
  activeOnly?: boolean;
  limit?: number;
  offset?: number;
};

export async function fetchTreatmentHolds(query: HoldQuery = {}): Promise<TreatmentHold[]> {
  const { customerId, activeOnly = true, limit, offset } = query;
  const params = new URLSearchParams({ activeOnly: String(activeOnly) });
  if (customerId) params.set("customerId", customerId);
  if (limit != null) params.set("limit", String(limit));
  if (offset != null) params.set("offset", String(offset));
  return apiGet<TreatmentHold[]>(`/treatment/holds?${params.toString()}`);
}

/**
 * Place a hold. Re-placing an active one returns the existing row rather than
 * a 409 — the backend is idempotent by design, so the UI must not treat a
 * second click as an error.
 */
export async function createTreatmentHold(input: TreatmentHoldInput): Promise<TreatmentHold> {
  const body: Record<string, unknown> = { customerId: input.customerId, kind: input.kind };
  // The backend forbids extra keys and rejects explicit nulls on optionals —
  // send only what the operator actually filled in.
  if (input.accountId) body.accountId = input.accountId;
  if (input.reason) body.reason = input.reason;
  if (input.source) body.source = input.source;
  if (input.interactionId) body.interactionId = input.interactionId;
  if (input.specialistUserId) body.specialistUserId = input.specialistUserId;
  if (input.slaDueAt) body.slaDueAt = input.slaDueAt;
  if (input.expiresAt) body.expiresAt = input.expiresAt;
  return apiPost<TreatmentHold>("/treatment/holds", body);
}

export async function releaseTreatmentHold(
  holdId: string,
  reason?: string | null,
): Promise<TreatmentHold> {
  return apiPost<TreatmentHold>(
    `/treatment/holds/${encodeURIComponent(holdId)}/release`,
    reason?.trim() ? { reason: reason.trim() } : {},
  );
}

export type CaseQuery = {
  customerId?: string | null;
  openOnly?: boolean;
  limit?: number;
  offset?: number;
};

export async function fetchTreatmentCases(query: CaseQuery = {}): Promise<TreatmentCase[]> {
  const { customerId, openOnly = true, limit, offset } = query;
  const params = new URLSearchParams({ openOnly: String(openOnly) });
  if (customerId) params.set("customerId", customerId);
  if (limit != null) params.set("limit", String(limit));
  if (offset != null) params.set("offset", String(offset));
  return apiGet<TreatmentCase[]>(`/treatment/cases?${params.toString()}`);
}

// ---------------------------------------------------------------------------
// Hooks
//
// staleTime is generous on the aggregates: they are rolling windows over the
// decision log, and refetching per render buys nothing but scans.
// ---------------------------------------------------------------------------

export function useTreatmentNext(
  customerId: string | null | undefined,
  accountId?: string | null,
  trigger = "manual",
) {
  return useQuery({
    queryKey: ["treatment-next", customerId, accountId ?? null, trigger],
    queryFn: () => fetchTreatmentNext(customerId!, accountId, trigger),
    // The engine writes a decision row on every call — never fire it without a
    // borrower, and never on a window refocus.
    enabled: Boolean(customerId),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}

export function useTreatmentInsights(days = 14) {
  return useQuery({
    queryKey: ["treatment-insights", days],
    queryFn: () => fetchTreatmentInsights(days),
    staleTime: 60_000,
  });
}

export function useTreatmentMetrics(days = 28, includeSimulated = false) {
  return useQuery({
    queryKey: ["treatment-metrics", days, includeSimulated],
    queryFn: () => fetchTreatmentMetrics(days, includeSimulated),
    staleTime: 60_000,
  });
}

export function useTreatmentModelHealth(days = 14, includeSimulated = false) {
  return useQuery({
    queryKey: ["treatment-model-health", days, includeSimulated],
    queryFn: () => fetchTreatmentModelHealth(days, includeSimulated),
    staleTime: 60_000,
  });
}

export function useTreatmentModels(target?: string | null, limit = 50) {
  return useQuery({
    queryKey: ["treatment-models", target ?? "all", limit],
    queryFn: () => fetchTreatmentModels(target, limit),
    staleTime: 60_000,
  });
}

export function useTreatmentHolds(query: HoldQuery = {}) {
  const { customerId = null, activeOnly = true, limit, offset } = query;
  return useQuery({
    queryKey: ["treatment-holds", customerId, activeOnly, limit ?? null, offset ?? null],
    queryFn: () => fetchTreatmentHolds({ customerId, activeOnly, limit, offset }),
  });
}

export function useTreatmentCases(query: CaseQuery = {}) {
  const { customerId = null, openOnly = true, limit, offset } = query;
  return useQuery({
    queryKey: ["treatment-cases", customerId, openOnly, limit ?? null, offset ?? null],
    queryFn: () => fetchTreatmentCases({ customerId, openOnly, limit, offset }),
  });
}

export function useCreateTreatmentHold() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: TreatmentHoldInput) => createTreatmentHold(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["treatment-holds"] });
      // A hold is a veto the engine reads, so the case ladder changes too.
      void qc.invalidateQueries({ queryKey: ["treatment-cases"] });
    },
  });
}

export function useReleaseTreatmentHold() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: ({ holdId, reason }: { holdId: string; reason?: string | null }) =>
      releaseTreatmentHold(holdId, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["treatment-holds"] });
      void qc.invalidateQueries({ queryKey: ["treatment-cases"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Formatting — null is a fact, not a zero.
// ---------------------------------------------------------------------------

/** `0.5779` → `"57.8%"`. Null renders as an em dash, never as "0%". */
export function fmtRate(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Indian digit grouping, no paise unless the figure is small enough to need it. */
export function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const body =
    abs >= 100
      ? Math.round(value).toLocaleString("en-IN")
      : value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `₹${body}`;
}

export function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * Tokens that keep their own capitalisation through sentence case.
 *
 * Without this, `whatsapp` renders as "Whatsapp" — a spelling the rest of the
 * app never uses (81 occurrences of "WhatsApp", none of "Whatsapp"), and the
 * kind of drift a design rule about sentence case is not meant to introduce.
 */
const PROPER_NOUNS: Record<string, string> = {
  whatsapp: "WhatsApp",
  sms: "SMS",
  ivr: "IVR",
  emi: "EMI",
  dpd: "DPD",
  ptp: "PTP",
  sla: "SLA",
  dnd: "DND",
  qa: "QA",
  crm: "CRM",
  auc: "AUC",
  psi: "PSI",
  ece: "ECE",
  ate: "ATE",
  ok: "OK",
};

/** `voice_bot` → `Voice bot`, `whatsapp` → `WhatsApp`. Sentence case otherwise. */
export function humanise(token: string | null | undefined): string {
  if (!token) return "—";
  const words = token.replace(/_/g, " ").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "—";
  const mapped = words.map((w) => PROPER_NOUNS[w.toLowerCase()] ?? w);
  // Capitalise the leading word unless it is a proper noun already spelled right.
  if (!(words[0].toLowerCase() in PROPER_NOUNS)) {
    mapped[0] = mapped[0].charAt(0).toUpperCase() + mapped[0].slice(1);
  }
  return mapped.join(" ");
}
