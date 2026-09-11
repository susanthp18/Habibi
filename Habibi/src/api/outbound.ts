// Outbound — attempts, missions, campaigns, cadence, obligations.
//
// Every number here was uncomputable before the attempt ledger: an unanswered
// dial left no row anywhere, because a CRM interaction is only created once
// media connects. Answer rate, right-party-contact rate and cost per connect
// were guesses, and the reach estimator was being fitted to its own numerator.

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

// -----------------------------------------------------------------------------
// Wire schemas — field-for-field with backend/schemas.py. A `datetime` is an
// ISO string on the wire. Where a value is `str` server-side but the column
// carries a CHECK constraint (sql/21_outbound.sql, sql/22_campaigns.sql) or the
// card model pins a Literal (agent_core/cards/schema.py), the enum here is that
// list; everything else is z.string(). Routes marked exclude_unset below get
// `.optional()` on every defaulted field.
// -----------------------------------------------------------------------------

const isoDate = z.string();
const isoDateOrNull = z.string().nullable();

/** ReachStatsResponse — every count is a float on the wire (`12.0`). */
const reachStatsSchema = z.object({
  attempts: z.number(),
  suppressed: z.number(),
  answered: z.number(),
  right_party: z.number(),
  voicemail: z.number(),
  invalid_number: z.number(),
  no_answer: z.number(),
  busy: z.number(),
  avg_ring_sec: z.number().nullable(),
  avg_talk_sec: z.number().nullable(),
  talk_sec_total: z.number().nullable(),
  answerRate: z.number().nullable(),
  rightPartyRate: z.number().nullable(),
  attemptsPerConnect: z.number().nullable(),
  windowDays: z.number(),
});

/** CallAttemptResponse — GET /outbound/attempts. */
const callAttemptSchema = z.object({
  id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  objective: z.string(),
  attempt_no: z.number(),
  state: z.string(),
  suppressed_reason: z.string().nullable(),
  to_phone_last4: z.string().nullable(),
  answered_by: z.string().nullable(),
  right_party: z.boolean().nullable(),
  ring_sec: z.number().nullable(),
  talk_sec: z.number().nullable(),
  provider_call_id: z.string().nullable(),
  provider_status: z.string().nullable(),
  provider_error: z.string().nullable(),
  interaction_id: z.string().nullable(),
  decision_id: z.string().nullable(),
  reserved_at: isoDate,
  placed_at: isoDateOrNull,
  answered_at: isoDateOrNull,
  ended_at: isoDateOrNull,
  connection: z.string().nullable(),
  business: z.string().nullable(),
  objective_met: z.boolean().nullable(),
  nonpayment_reason: z.string().nullable(),
  summary: z.string().nullable(),
  summary_source: z.string().nullable(),
});

/** MissionsResponse — GET /outbound/missions. direction / poolKind are card Literals. */
const missionsSchema = z.object({
  botId: z.string(),
  direction: z.enum(["inbound", "outbound", "both"]),
  poolKind: z.enum(["service_1600", "promotional", "general"]),
  numberPool: z.string().nullable(),
  objectives: z.array(
    z.object({
      key: z.string(),
      entryNode: z.string(),
      graphEntryNode: z.string().nullable(),
      agrees: z.boolean(),
      maxDurationSec: z.number(),
      allowedOffers: z.array(z.string()),
      authorityProfile: z.string().nullable(),
      cadence: z.string(),
      success: z.array(z.string()),
      brief: z.string(),
    }),
  ),
  graphEntries: z.record(z.string()),
  available: z.array(z.string()),
});

/** OutboundCardVocabularyResponse — the closed lists are the card model's Literals. */
const outboundVocabularySchema = z.object({
  objectives: z.array(z.string()),
  objectiveBriefs: z.record(z.string()),
  directions: z.array(z.enum(["inbound", "outbound", "both"])),
  voicemailModes: z.array(z.enum(["always", "never", "first_attempt_only", "engine"])),
  poolKinds: z.array(z.enum(["service_1600", "promotional", "general"])),
  qaModes: z.array(z.enum(["always", "sampled", "never"])),
  outcomeCodes: z.array(z.string()),
  postCallActions: z.array(z.string()),
  retryStates: z.array(z.string()),
  authorityProfiles: z.array(z.object({ name: z.string(), ceilingInr: z.number().nullable() })),
  numberPools: z.array(z.object({ name: z.string(), kind: z.string() })),
  dailyCap: z.number(),
});

/**
 * CampaignRunResponse — list / create / status all set response_model_exclude_unset,
 * so every defaulted field may be absent; `status` is campaign_runs' CHECK list.
 */
const campaignRunSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  bot_id: z.string().nullable().optional(),
  deployment_id: z.string().nullable().optional(),
  name: z.string(),
  objective: z.string(),
  cadence: z.string(),
  source: z.string(),
  selector: z.record(z.unknown()).optional(),
  status: z.enum(["draft", "running", "paused", "finished", "cancelled"]),
  window_start_hour: z.number(),
  window_end_hour: z.number(),
  max_concurrent: z.number(),
  max_attempts_total: z.number().nullable().optional(),
  targets_total: z.number(),
  targets_done: z.number(),
  created_by_user_id: z.string().nullable().optional(),
  started_at: isoDateOrNull.optional(),
  paused_at: isoDateOrNull.optional(),
  finished_at: isoDateOrNull.optional(),
  created_at: isoDate,
  updated_at: isoDate,
  pending: z.number().nullable().optional(),
  done: z.number().nullable().optional(),
  skipped: z.number().nullable().optional(),
  progress: z
    .object({
      total: z.number(),
      pending: z.number(),
      dialing: z.number(),
      done: z.number(),
      skipped: z.number(),
      failed: z.number(),
    })
    .nullable()
    .optional(),
});

/** CampaignCohortPreviewResponse — POST /outbound/campaigns/preview. */
const cohortPreviewSchema = z.object({
  matched: z.number(),
  capped: z.boolean(),
  sample: z.array(
    z.object({
      customer_id: z.string(),
      name: z.string(),
      risk: z.string(),
      account_id: z.string(),
      dpd: z.number(),
      bucket: z.string().nullable(),
      outstanding: z.number(),
    }),
  ),
});

/** CadenceCaseResponse — `state` is cadence_cases' CHECK list. */
const cadenceCaseSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  customer_id: z.string(),
  objective: z.string(),
  case_ref: z.string(),
  cadence: z.string(),
  attempts: z.number(),
  max_attempts: z.number(),
  next_attempt_at: isoDateOrNull,
  last_attempt_id: z.string().nullable(),
  last_outcome: z.string().nullable(),
  state: z.enum(["open", "exhausted", "stopped", "escalated"]),
  stopped_reason: z.string().nullable(),
  campaign_run_id: z.string().nullable(),
  bot_id: z.string().nullable(),
  escalate_to: z.string().nullable(),
  created_at: isoDate,
  updated_at: isoDate,
  customer_name: z.string(),
});

/** NumberPoolResponse — `kind` and `state` are number_pools' / pool_numbers' CHECK lists. */
const numberPoolSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  kind: z.enum(["service_1600", "promotional", "general"]),
  enabled: z.boolean(),
  created_at: isoDate,
  updated_at: isoDate,
  numbers: z.array(
    z.object({
      id: z.string(),
      pool_id: z.string(),
      e164: z.string(),
      state: z.enum(["active", "cooling", "retired"]),
      last_used_at: isoDateOrNull,
      attempts_7d: z.number(),
      answer_rate_7d: z.number().nullable(),
      state_changed_at: isoDate,
      health_checked_at: isoDateOrNull,
      note: z.string().nullable(),
      created_at: isoDate,
      updated_at: isoDate,
    }),
  ),
});

/** NonpaymentReasonResponse — GET /outbound/reasons. */
const reasonCountSchema = z.object({ reason: z.string(), calls: z.number(), resolved: z.number() });

/** AgentObligationResponse — `state` is agent_obligations' CHECK list. */
const agentObligationSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  customer_id: z.string(),
  interaction_id: z.string().nullable(),
  attempt_id: z.string().nullable(),
  kind: z.string(),
  due_at: isoDate,
  detail: z.record(z.unknown()),
  verbatim: z.string().nullable(),
  state: z.enum(["open", "honoured", "missed", "cancelled"]),
  honoured_at: isoDateOrNull,
  honoured_ref: z.string().nullable(),
  created_at: isoDate,
  updated_at: isoDate,
  customer_name: z.string(),
});

/** TwilioOutboundCallResponse — three branches share one model, exclude_unset. */
const placedCallSchema = z.object({
  placed: z.boolean().nullable().optional(),
  attemptId: z.string().nullable().optional(),
  state: z.string().nullable().optional(),
  idempotent: z.boolean().nullable().optional(),
  to: z.string().nullable().optional(),
  callSid: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  from: z.string().nullable().optional(),
});
import { OBJECTIVES } from "./agent-card";

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
  provider_call_id: string | null;
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
  pending?: number | null;
  done?: number | null;
  skipped?: number | null;
  started_at?: string | null;
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
  available: [...OBJECTIVES],
};

export async function fetchReachStats(days = 14): Promise<ReachStats> {
  if (USE_MOCK) {
    return mockDelay(MOCK_STATS);
  }
  return apiGet<ReachStats>(`/outbound/stats?days=${days}`, { schema: reachStatsSchema });
}

export async function fetchAttempts(params: { customerId?: string; limit?: number } = {}) {
  if (USE_MOCK) {
    return mockDelay([] as CallAttempt[]);
  }
  const q = new URLSearchParams();
  if (params.customerId) q.set("customerId", params.customerId);
  q.set("limit", String(params.limit ?? 50));
  return apiGet<CallAttempt[]>(`/outbound/attempts?${q.toString()}`, {
    schema: z.array(callAttemptSchema),
  });
}

export async function fetchMissions(botId?: string): Promise<MissionConfig> {
  if (USE_MOCK) {
    return mockDelay(MOCK_MISSIONS);
  }
  // Scoped to the card being edited. Without the bot the endpoint answers for
  // the default one, and the Outbound tab renders that under whatever card you
  // happen to have open.
  const q = botId ? `?botId=${encodeURIComponent(botId)}` : "";
  return apiGet<MissionConfig>(`/outbound/missions${q}`, { schema: missionsSchema });
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
  return apiGet<OutboundVocabulary>("/outbound/card-vocabulary", {
    schema: outboundVocabularySchema,
  });
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
  return apiGet<CampaignRun[]>("/outbound/campaigns", { schema: z.array(campaignRunSchema) });
}

/**
 * Caller-ID pools — GET /outbound/number-pools (NumberPoolResponse, a row-star,
 * hence snake_case). Mirrors sql/22_campaigns.sql.
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
  return apiGet<NumberPool[]>("/outbound/number-pools", { schema: z.array(numberPoolSchema) });
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
  return apiGet<CadenceCase[]>("/outbound/cadence?limit=50", {
    schema: z.array(cadenceCaseSchema),
  });
}

export async function fetchReasons(days = 30): Promise<ReasonCount[]> {
  if (USE_MOCK) {
    return mockDelay([]);
  }
  return apiGet<ReasonCount[]>(`/outbound/reasons?days=${days}`, {
    schema: z.array(reasonCountSchema),
  });
}

export async function fetchObligations(): Promise<AgentObligation[]> {
  if (USE_MOCK) {
    return mockDelay([]);
  }
  return apiGet<AgentObligation[]>("/outbound/obligations?state=open", {
    schema: z.array(agentObligationSchema),
  });
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
    meta: { errors: "caller" },
    mutationFn: async (selector: CampaignSelector) =>
      apiPost<CohortPreview>(
        "/outbound/campaigns/preview",
        { selector, sample: 8 },
        { schema: cohortPreviewSchema },
      ),
  });
}

/** Create a run in `draft`. Bringing a campaign into existence and setting it
 *  going stay two deliberate acts — this one does not dial. */
export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (payload: {
      name: string;
      objective: string;
      botId?: string;
      cadence?: string;
      selector?: CampaignSelector;
      windowStartHour?: number;
      windowEndHour?: number;
      maxConcurrent?: number;
    }) => apiPost<CampaignRun>("/outbound/campaigns", payload, { schema: campaignRunSchema }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outbound", "campaigns"] }),
  });
}

/** What the dial owner reports back for one operator-placed call. */
export type PlacedCall = z.infer<typeof placedCallSchema>;

/**
 * Place one call to a customer through the dial owner -- reserve, admit,
 * suppress-or-place, every gate. A refusal (statutory window, DND, caps)
 * comes back as a 409 with its reason; the caller shows it, because the
 * refusal is the product working. The key makes a retried click one attempt.
 */
export function usePlaceCall() {
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: ({
      customerId,
      phone,
      idempotencyKey,
    }: {
      customerId: string;
      phone: string;
      idempotencyKey: string;
    }) =>
      apiPost<PlacedCall>(
        "/twilio/voice/outbound",
        { customerId, to: phone, objective: "manual_outbound" },
        { headers: { "Idempotency-Key": idempotencyKey }, schema: placedCallSchema },
      ),
  });
}

export function useSetCampaignStatus() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: async ({ runId, status }: { runId: string; status: string }) =>
      apiPost(`/outbound/campaigns/${runId}/status`, { status }, { schema: campaignRunSchema }),
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
