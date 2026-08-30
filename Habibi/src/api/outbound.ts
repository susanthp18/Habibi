// Outbound — attempts, missions, campaigns, cadence, obligations.
//
// Every number here was uncomputable before the attempt ledger: an unanswered
// dial left no row anywhere, because a CRM interaction is only created once
// media connects. Answer rate, right-party-contact rate and cost per connect
// were guesses, and the reach estimator was being fitted to its own numerator.

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

export type ReachStats = {
  attempts: number;
  suppressed: number;
  answered: number;
  right_party: number;
  voicemail: number;
  invalid_number: number;
  no_answer: number;
  busy: number;
  avg_ring_sec: number | null;
  avg_talk_sec: number | null;
  talk_sec_total: number | null;
  answerRate: number | null;
  rightPartyRate: number | null;
  attemptsPerConnect: number | null;
  windowDays: number;
};

export type CallAttempt = {
  id: string;
  customer_id: string;
  customer_name: string | null;
  objective: string;
  attempt_no: number;
  state: string;
  suppressed_reason: string | null;
  to_phone_last4: string | null;
  answered_by: string | null;
  right_party: boolean | null;
  ring_sec: number | null;
  talk_sec: number | null;
  provider_status: string | null;
  provider_error: string | null;
  interaction_id: string | null;
  decision_id: string | null;
  reserved_at: string;
  placed_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  connection: string | null;
  business: string | null;
  objective_met: boolean | null;
  nonpayment_reason: string | null;
  summary: string | null;
  summary_source: string | null;
};

/** A declarative cohort. The backend refuses any key not in this shape rather
 *  than ignoring it — a selector field that is silently dropped produces a run
 *  that looks like the one you wrote and calls a different population. */
export type CampaignSelector = {
  buckets?: string[];
  dpdMin?: number;
  dpdMax?: number;
  minOutstandingInr?: number;
  maxOutstandingInr?: number;
  risk?: string[];
  language?: string[];
  excludeOpenPromise?: boolean;
  excludeOnHold?: boolean;
  excludeContactedWithinDays?: number;
  limit?: number;
};

export type CohortMember = {
  customer_id: string;
  name: string | null;
  risk: string | null;
  account_id: string | null;
  dpd: number | null;
  bucket: string | null;
  outstanding: number | string | null;
};

export type CohortPreview = {
  matched: number;
  capped: boolean;
  sample: CohortMember[];
};

export type MissionSummary = {
  key: string;
  entryNode: string;
  graphEntryNode: string | null;
  /** False means the card and the graph disagree — the failure G-OB2 catches. */
  agrees: boolean;
  maxDurationSec: number;
  allowedOffers: string[];
  authorityProfile: string | null;
  cadence: string;
  success: string[];
  brief: string;
};

export type MissionConfig = {
  botId: string;
  direction: "inbound" | "outbound" | "both";
  poolKind: "service_1600" | "promotional" | "general";
  numberPool: string | null;
  objectives: MissionSummary[];
  graphEntries: Record<string, string>;
  available: string[];
};

export type CampaignRun = {
  id: string;
  name: string;
  objective: string;
  cadence: string;
  status: "draft" | "running" | "paused" | "finished" | "cancelled";
  window_start_hour: number;
  window_end_hour: number;
  max_concurrent: number;
  targets_total: number;
  targets_done: number;
  pending?: number;
  done?: number;
  skipped?: number;
  started_at: string | null;
  created_at: string;
};

export type CadenceCase = {
  id: string;
  customer_id: string;
  customer_name: string | null;
  objective: string;
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_outcome: string | null;
  state: "open" | "exhausted" | "stopped" | "escalated";
  stopped_reason: string | null;
};

export type ReasonCount = { reason: string; calls: number; resolved: number };

export type AgentObligation = {
  id: string;
  customer_id: string;
  customer_name: string | null;
  kind: string;
  due_at: string;
  state: "open" | "honoured" | "missed" | "cancelled";
  verbatim: string | null;
};

// Mock shapes exist so the Studio tab renders without a backend. They are
// deliberately unremarkable numbers: a mock answer rate of 92% would make the
// tab look like it was reporting something it is not.
const MOCK_STATS: ReachStats = {
  attempts: 0,
  suppressed: 0,
  answered: 0,
  right_party: 0,
  voicemail: 0,
  invalid_number: 0,
  no_answer: 0,
  busy: 0,
  avg_ring_sec: null,
  avg_talk_sec: null,
  talk_sec_total: null,
  answerRate: null,
  rightPartyRate: null,
  attemptsPerConnect: null,
  windowDays: 14,
};

const MOCK_MISSIONS: MissionConfig = {
  botId: "kaia-v2-4",
  direction: "inbound",
  poolKind: "general",
  numberPool: null,
  objectives: [],
  graphEntries: {},
  available: [
    "inbound",
    "pre_due_reminder",
    "bounce_cure",
    "dpd_reminder",
    "broken_ptp_chase",
    "hardship_intake",
    "mandate_reregistration",
    "document_chase",
    "callback_honour",
    "welcome_onboarding",
    "retention_save",
    "cross_sell",
    "manual_outbound",
  ],
};

export async function fetchReachStats(days = 14): Promise<ReachStats> {
  if (USE_MOCK) {
    return mockDelay(MOCK_STATS);
  }
  return apiGet<ReachStats>(`/outbound/stats?days=${days}`);
}

export async function fetchAttempts(params: { customerId?: string; limit?: number } = {}) {
  if (USE_MOCK) {
    return mockDelay([] as CallAttempt[]);
  }
  const q = new URLSearchParams();
  if (params.customerId) q.set("customerId", params.customerId);
  q.set("limit", String(params.limit ?? 50));
  return apiGet<CallAttempt[]>(`/outbound/attempts?${q.toString()}`);
}

export async function fetchMissions(botId?: string): Promise<MissionConfig> {
  if (USE_MOCK) {
    return mockDelay(MOCK_MISSIONS);
  }
  // Scoped to the card being edited. Without the bot the endpoint answers for
  // the default one, and the Outbound tab renders that under whatever card you
  // happen to have open.
  const q = botId ? `?botId=${encodeURIComponent(botId)}` : "";
  return apiGet<MissionConfig>(`/outbound/missions${q}`);
}

/**
 * Every closed vocabulary the Outbound card editor offers, from the backend.
 *
 * Deliberately not a set of constants in this file. `card.outbound` is
 * validated by Pydantic models with `extra="forbid"` and gated by G-OB1..8, so
 * a value this editor offers that the backend does not know does not degrade —
 * it builds a card that cannot be published, and the author meets the failure
 * at the publish button holding an option they picked from a dropdown. Every
 * list here is derived server-side from the definition the runtime uses.
 */
export type OutboundVocabulary = {
  objectives: string[];
  objectiveBriefs: Record<string, string>;
  directions: Array<"inbound" | "outbound" | "both">;
  voicemailModes: Array<"always" | "never" | "first_attempt_only" | "engine">;
  timeOfDay: Array<"engine" | "fixed" | "spread">;
  poolKinds: Array<"service_1600" | "promotional" | "general">;
  qaModes: Array<"always" | "sampled" | "never">;
  /** The Closer's taxonomy — `success`, `partial`, `stop_on`, and a post-call
   *  rule's `when`. G-OB6 rejects anything outside it. */
  outcomeCodes: string[];
  /** Verbs the Closer implements. A rule may also name a tool on the card. */
  postCallActions: string[];
  /** Attempt states worth another dial — the offerable set for `retry_on`. */
  retryStates: string[];
  authorityProfiles: Array<{ name: string; ceilingInr: number | null }>;
  numberPools: Array<{ name: string; kind: string }>;
  /** `contact_policy`'s per-borrower daily cap. G-OB3 fails a cadence over it,
   *  so the editor can say so while the number is being typed. */
  dailyCap: number;
};

const EMPTY_VOCABULARY: OutboundVocabulary = {
  objectives: [],
  objectiveBriefs: {},
  directions: ["inbound", "outbound", "both"],
  voicemailModes: ["always", "never", "first_attempt_only", "engine"],
  timeOfDay: ["engine", "fixed", "spread"],
  poolKinds: ["service_1600", "promotional", "general"],
  qaModes: ["always", "sampled", "never"],
  outcomeCodes: [],
  postCallActions: [],
  retryStates: [],
  authorityProfiles: [],
  numberPools: [],
  dailyCap: 3,
};

export async function fetchOutboundVocabulary(): Promise<OutboundVocabulary> {
  if (USE_MOCK) return mockDelay(EMPTY_VOCABULARY);
  return apiGet<OutboundVocabulary>("/outbound/card-vocabulary");
}

export function useOutboundVocabulary() {
  return useQuery({
    queryKey: ["outbound", "card-vocabulary"],
    queryFn: fetchOutboundVocabulary,
    // These change when the backend is deployed, not while a card is open.
    staleTime: 10 * 60_000,
  });
}

export async function fetchCampaigns(): Promise<CampaignRun[]> {
  if (USE_MOCK) {
    return mockDelay([]);
  }
  return apiGet<CampaignRun[]>("/outbound/campaigns");
}

/**
 * Caller-ID pools — GET /outbound/number-pools.
 *
 * This endpoint has no response_model on the server: it returns raw table rows,
 * so these field names ARE the contract and they are snake_case, unlike every
 * other type in this file. Mirrors sql/22_campaigns.sql.
 */
export type PoolNumber = {
  id: string;
  pool_id: string;
  e164: string;
  state: "active" | "cooling" | "retired";
  last_used_at: string | null;
  attempts_7d: number;
  /** Null when the sweep has not scored the number yet. Never render it as 0%. */
  answer_rate_7d: number | null;
  state_changed_at: string;
  health_checked_at: string | null;
  note: string | null;
};

export type NumberPool = {
  id: string;
  tenant_id: string;
  name: string;
  /** TRAI reserves the 1600 series for BFSI service calls — no promotions on it. */
  kind: "service_1600" | "promotional" | "general";
  enabled: boolean;
  created_at: string;
  updated_at: string;
  numbers: PoolNumber[];
};

const MOCK_NUMBER_POOLS: NumberPool[] = [
  {
    id: "NP-mock-service",
    tenant_id: "mock",
    name: "Service 1600",
    kind: "service_1600",
    enabled: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    numbers: [
      {
        id: "PN-mock-1",
        pool_id: "NP-mock-service",
        e164: "+911600100001",
        state: "active",
        last_used_at: "2026-08-22T09:10:00Z",
        attempts_7d: 214,
        answer_rate_7d: 0.3178,
        state_changed_at: "2026-08-01T00:00:00Z",
        health_checked_at: "2026-08-23T03:00:00Z",
        note: null,
      },
      {
        id: "PN-mock-2",
        pool_id: "NP-mock-service",
        e164: "+911600100002",
        state: "cooling",
        last_used_at: "2026-08-20T14:02:00Z",
        attempts_7d: 96,
        answer_rate_7d: 0.0521,
        state_changed_at: "2026-08-21T06:00:00Z",
        health_checked_at: "2026-08-23T03:00:00Z",
        note: "answer rate collapsed",
      },
      {
        id: "PN-mock-3",
        pool_id: "NP-mock-service",
        e164: "+911600100003",
        state: "active",
        last_used_at: null,
        attempts_7d: 0,
        // Not enough volume to judge. A rate over four dials is noise, so the
        // sweep declines to invent one.
        answer_rate_7d: null,
        state_changed_at: "2026-08-01T00:00:00Z",
        health_checked_at: "2026-08-23T03:00:00Z",
        note: null,
      },
    ],
  },
];

export async function fetchNumberPools(): Promise<NumberPool[]> {
  if (USE_MOCK) {
    return mockDelay(MOCK_NUMBER_POOLS);
  }
  return apiGet<NumberPool[]>("/outbound/number-pools");
}

/**
 * Polled: bot_worker runs outbound.sweep_pool_health every settle cycle, so a
 * number can be cooled or restored while this pane is open and nobody would
 * otherwise see it happen.
 */
export function useNumberPools() {
  return useQuery({
    queryKey: ["outbound", "number-pools"],
    queryFn: fetchNumberPools,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export async function fetchCadenceCases(): Promise<CadenceCase[]> {
  if (USE_MOCK) {
    return mockDelay([]);
  }
  return apiGet<CadenceCase[]>("/outbound/cadence?limit=50");
}

export async function fetchReasons(days = 30): Promise<ReasonCount[]> {
  if (USE_MOCK) {
    return mockDelay([]);
  }
  return apiGet<ReasonCount[]>(`/outbound/reasons?days=${days}`);
}

export async function fetchObligations(): Promise<AgentObligation[]> {
  if (USE_MOCK) {
    return mockDelay([]);
  }
  return apiGet<AgentObligation[]>("/outbound/obligations?state=open");
}

export function useReachStats(days = 14) {
  return useQuery({ queryKey: ["outbound", "stats", days], queryFn: () => fetchReachStats(days) });
}

export function useOutboundAttempts(customerId?: string) {
  return useQuery({
    queryKey: ["outbound", "attempts", customerId ?? "all"],
    queryFn: () => fetchAttempts({ customerId }),
  });
}

export function useMissions(botId?: string) {
  return useQuery({
    // botId is in the key: cached under a bare "missions" key, switching cards
    // served the previous card's answer from cache before the refetch landed.
    queryKey: ["outbound", "missions", botId ?? "default"],
    queryFn: () => fetchMissions(botId),
  });
}

export function useCampaigns() {
  return useQuery({ queryKey: ["outbound", "campaigns"], queryFn: fetchCampaigns });
}

export function useCadenceCases() {
  return useQuery({ queryKey: ["outbound", "cadence"], queryFn: fetchCadenceCases });
}

export function useNonpaymentReasons(days = 30) {
  return useQuery({ queryKey: ["outbound", "reasons", days], queryFn: () => fetchReasons(days) });
}

export function useObligations() {
  return useQuery({ queryKey: ["outbound", "obligations"], queryFn: fetchObligations });
}

/** Count the cohort before a run exists. Nothing is created and nothing dials. */
export function usePreviewCohort() {
  return useMutation({
    mutationFn: async (selector: CampaignSelector) =>
      apiPost<CohortPreview>("/outbound/campaigns/preview", { selector, sample: 8 }),
  });
}

/** Create a run in `draft`. Bringing a campaign into existence and setting it
 *  going stay two deliberate acts — this one does not dial. */
export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      name: string;
      objective: string;
      botId?: string;
      cadence?: string;
      selector?: CampaignSelector;
      windowStartHour?: number;
      windowEndHour?: number;
      maxConcurrent?: number;
    }) => apiPost<CampaignRun>("/outbound/campaigns", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outbound", "campaigns"] }),
  });
}

export function useSetCampaignStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ runId, status }: { runId: string; status: string }) =>
      apiPost(`/outbound/campaigns/${runId}/status`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outbound", "campaigns"] }),
  });
}

/** Human label for an attempt state. The raw values are for queries, not people. */
export const ATTEMPT_STATE_LABEL: Record<string, string> = {
  reserved: "reserved",
  suppressed: "blocked by policy",
  dialing: "dialling",
  ringing: "ringing",
  answered: "answered",
  live: "on the call",
  completed: "completed",
  voicemail_left: "voicemail left",
  voicemail_skipped: "voicemail skipped",
  no_answer: "no answer",
  busy: "busy",
  rejected: "rejected",
  failed: "carrier error",
  invalid_number: "bad number",
  canceled: "cancelled",
  transferred: "transferred",
  abandoned: "abandoned",
};

export const REASON_LABEL: Record<string, string> = {
  salary_timing: "Salary lands after the EMI date",
  income_loss: "Lost income",
  medical: "Medical",
  mandate_broken: "Auto-debit broken",
  disputes_amount: "Disputes the amount",
  competing_obligation: "Paying someone else first",
  forgot: "Forgot",
  unwilling: "Able, refusing",
  not_stated: "Would not say",
};
