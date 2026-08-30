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

import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

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
  decisionId: string;
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
// Mock seed — an Indian collections book mid-shadow-rollout.
//
// Deliberately shaped like a real fortnight: mostly shadow decisions, a
// suppression mix dominated by shadow_mode, one thin arm that cannot support a
// causal number, and a serving check that disagrees with the registry. A seed
// where everything is green teaches the UI nothing.
// ---------------------------------------------------------------------------

const mockInsights: TreatmentInsights = {
  windowDays: 14,
  decisions: 1284,
  actionable: 742,
  coverage: 0.5779,
  enacted: 0,
  customers: 913,
  expectedValueInr: 48_216.4,
  avgLatencyMs: 184,
  suppression: [
    { reason: "shadow_mode", count: 742 },
    { reason: "no_eligible_action", count: 318 },
    { reason: "quiet_hours", count: 121 },
    { reason: "daily_cap_reached", count: 63 },
    { reason: "hardship_hold", count: 28 },
    { reason: "dnd_registry", count: 12 },
  ],
  byAction: [
    { action: "whatsapp", count: 306, avgExpectedValue: 58.42 },
    { action: "voice_bot", count: 214, avgExpectedValue: 71.06 },
    { action: "sms", count: 118, avgExpectedValue: 22.85 },
    { action: "human_call", count: 74, avgExpectedValue: 96.31 },
    { action: "self_service_plan", count: 21, avgExpectedValue: 143.7 },
    { action: "field_visit", count: 9, avgExpectedValue: 188.24 },
  ],
  byMode: [
    { mode: "shadow", count: 1208 },
    { mode: "live", count: 76 },
  ],
  outcomes: [
    { outcome: "ptp", count: 41 },
    { outcome: "paid", count: 28 },
    { outcome: "no_answer", count: 19 },
    { outcome: "refused", count: 7 },
  ],
};

const mockModelHealth: TreatmentModelHealth = {
  windowDays: 14,
  decisions: 1284,
  sampleLimit: 20_000,
  truncated: false,
  driftSampled: 1284,
  driftSampleLimit: 2000,
  reachCalibration: {
    n: 612,
    ece: 0.043,
    quantity: "P(attempt reaches a human)",
    bins: [
      { bin: 0.1, n: 74, predicted: 0.092, observed: 0.108 },
      { bin: 0.3, n: 138, predicted: 0.291, observed: 0.246 },
      { bin: 0.5, n: 181, predicted: 0.503, observed: 0.541 },
      { bin: 0.7, n: 142, predicted: 0.698, observed: 0.662 },
      { bin: 0.9, n: 77, predicted: 0.884, observed: 0.909 },
    ],
  },
  upliftCalibration: {
    available: false,
    reason: "needs labelled outcomes in both the treated and the control arm",
    treatedN: 76,
    controlN: 34,
  },
  featureDrift: {
    available: true,
    features: [
      { feature: "dpd", psi: 0.061, drifted: false },
      { feature: "outstanding", psi: 0.118, drifted: false },
      { feature: "prior_contacts_7d", psi: 0.264, drifted: true },
      { feature: "salary_day_gap", psi: 0.039, drifted: false },
      { feature: "mandate_state", psi: 0.087, drifted: false },
    ],
  },
  models: { reach: "202608180931", uplift: "202608211146", upliftSegments: 1 },
  alerts: [
    {
      metric: "featureDrift.prior_contacts_7d",
      message: "PSI 0.26 over the 0.20 threshold — the contact-history feature has shifted",
    },
  ],
};

const mockMetrics: TreatmentMetrics = {
  windowDays: 28,
  causal: {
    available: false,
    reason:
      "control arm holds 34 and the treated arm 76 labelled cases (need 100 each). Without both there is no causal number here, only a collections rate — and a collections rate is exactly what this scoreboard exists not to report.",
    controlN: 34,
    treatedN: 76,
  },
  efficiency: {
    resolutions: 69,
    contacts: 512,
    voiceMinutes: 863.4,
    voiceCalls: 402,
    contactsPerResolution: 7.42,
    voiceMinutesPerResolution: 12.51,
    voiceMinutesPerLakhRecovered: 41.3,
    recoveredInr: 2_090_400,
  },
  modelHealth: mockModelHealth,
  compliance: {
    attempts: 512,
    allowed: 498,
    denied: 14,
    denialRate: 0.0273,
    denialsByReason: [
      { reason: "quiet_hours", n: 9 },
      { reason: "dnd_registry", n: 5 },
    ],
    windowBreaches: 0,
    capBreaches: 0,
    worstDayTouches: 3,
    dailyCap: 3,
    breaches: 0,
    breachTarget: 0,
    breachNote: "none — every allowed outbound contact was inside its window and cap",
    optOuts: 4,
    complaints: {
      available: false,
      reason:
        "no conduct-complaint source in the schema — disputes.type carries billing disputes only. Needs a complaint intake before this can be a number.",
    },
  },
  borrowerExperience: {
    cases: 913,
    contactsPerCase: 0.56,
    worstCaseContacts: 6,
    casesOverFiveContacts: 3,
    heavyCaseShare: 0.0033,
  },
  capacity: {
    solved: true,
    resources: [
      {
        resource: "agent_minutes",
        daysSolved: 28,
        avgDualPriceInr: 2.14,
        priceSpreadInr: 0.62,
        stability: "stable",
        utilisation: 0.81,
        nonConvergedDays: 0,
      },
      {
        resource: "bot_minutes",
        daysSolved: 28,
        avgDualPriceInr: 0.18,
        priceSpreadInr: 0.04,
        stability: "stable",
        utilisation: 0.44,
        nonConvergedDays: 0,
      },
      {
        resource: "field_slots",
        daysSolved: 28,
        avgDualPriceInr: 61.5,
        priceSpreadInr: 24.8,
        stability: "volatile",
        utilisation: 0.97,
        nonConvergedDays: 2,
      },
      {
        resource: "mandate_presentations",
        daysSolved: 28,
        avgDualPriceInr: 0,
        priceSpreadInr: 0,
        stability: "unpriced",
        utilisation: 0.12,
        nonConvergedDays: 0,
      },
    ],
  },
};

const mockModels: TreatmentModels = {
  history: [
    {
      id: "TMR-0665959AEC38",
      target: "uplift",
      version: "202608211146",
      status: "challenger",
      corpus: "simulated",
      n_samples: 14_331,
      control_n: 3668,
      segments_promoted: 1,
      registered_at: "2026-08-21T12:14:16.328902+00:00",
      promoted_at: null,
      promoted_by: null,
      retired_at: null,
      reason: null,
      metrics: {
        ate: 0.179359,
        baseRate: 0.520689,
        holdoutN: 3583,
        holdoutAuc: 0.7191,
        controlRate: 0.34133,
        segmentsPromoted: 1,
        segmentLadder: [
          {
            segment: "b0030/open/timing",
            label: "0-30 DPD, reachable, salary-timing",
            verdict: "promoted",
            ate: 0.220238,
            ateStderr: 0.014511,
            z: 2.817,
            zRequired: 2.498,
            controlN: 1313,
            treatedN: 4612,
            holdoutLift: 0.000765,
          },
          {
            segment: "b0030/open/capacity",
            label: "0-30 DPD, reachable, capacity",
            verdict: "rejected",
            reason: "no_holdout_lift",
            ate: 0.056769,
            ateStderr: 0.018261,
            z: 6.713,
            zRequired: 2.498,
            controlN: 907,
            treatedN: 3755,
            holdoutLift: -0.012374,
          },
          {
            segment: "b3160/open/capacity",
            verdict: "skipped",
            reason: "underpowered",
            controlN: 101,
            treatedN: 589,
          },
        ],
      },
    },
    {
      id: "TMR-3A17C0D94B21",
      target: "reach",
      version: "202608180931",
      status: "champion",
      corpus: "production",
      n_samples: 22_804,
      control_n: 0,
      segments_promoted: 0,
      registered_at: "2026-08-18T09:31:44.101233+00:00",
      promoted_at: "2026-08-18T10:02:11.884120+00:00",
      promoted_by: "Meera Iyer",
      retired_at: null,
      reason: "AUC 0.74 on holdout, ECE 0.04 — beat the incumbent on both",
      metrics: { holdoutN: 5701, holdoutAuc: 0.7412, baseRate: 0.4183 },
    },
    {
      id: "TMR-9F42B7E10C55",
      target: "reach",
      version: "202607290812",
      status: "retired",
      corpus: "production",
      n_samples: 18_990,
      control_n: 0,
      segments_promoted: 0,
      registered_at: "2026-07-29T08:12:03.552901+00:00",
      promoted_at: "2026-07-29T09:40:00.000000+00:00",
      promoted_by: "Meera Iyer",
      retired_at: "2026-08-18T10:02:11.884120+00:00",
      reason: "superseded by 202608180931",
      metrics: { holdoutN: 4802, holdoutAuc: 0.7038, baseRate: 0.4106 },
    },
  ],
  serving: [
    { target: "reach", state: "ok", detail: "serving 202608180931, the promoted champion" },
    {
      target: "uplift",
      state: "unregistered",
      detail: "a file is serving that no promotion produced",
    },
    { target: "timing", state: "missing", detail: "no artifact on disk — falling back to priors" },
  ],
};

const mockHolds: TreatmentHold[] = [
  {
    id: "THD-4C1A9B2E",
    customerId: "priya-sharma",
    customerName: "Priya Sharma",
    accountId: "AC-90881",
    kind: "hardship",
    reason: "Lost job at the Pune plant, asked for 60 days",
    source: "bot",
    interactionId: "INT-88213",
    slaDueAt: "2026-08-27T09:00:00+00:00",
    startsAt: "2026-08-20T11:42:00+00:00",
    expiresAt: "2026-10-19T11:42:00+00:00",
    releasedAt: null,
    releasedReason: null,
    placedBy: "Voice bot",
    specialist: "Meera Iyer",
    active: true,
    createdAt: "2026-08-20T11:42:00+00:00",
  },
  {
    id: "THD-77E30D18",
    customerId: "rakesh-menon",
    customerName: "Rakesh Menon",
    accountId: "AC-91204",
    kind: "dispute",
    reason: "Disputes the ₹1,180 late fee charged twice in June",
    source: "manual",
    interactionId: null,
    slaDueAt: "2026-08-25T09:00:00+00:00",
    startsAt: "2026-08-18T06:15:00+00:00",
    expiresAt: null,
    releasedAt: null,
    releasedReason: null,
    placedBy: "Anand Krishnan",
    specialist: null,
    active: true,
    createdAt: "2026-08-18T06:15:00+00:00",
  },
  {
    id: "THD-1B9F5C40",
    customerId: "lakshmi-venkatesan",
    customerName: "Lakshmi Venkatesan",
    accountId: "AC-89330",
    kind: "bereavement",
    reason: "Spouse deceased — family requested no contact for 90 days",
    source: "manual",
    interactionId: null,
    slaDueAt: null,
    startsAt: "2026-07-30T04:00:00+00:00",
    expiresAt: "2026-10-28T04:00:00+00:00",
    releasedAt: null,
    releasedReason: null,
    placedBy: "Sunita Rao",
    specialist: "Sunita Rao",
    active: true,
    createdAt: "2026-07-30T04:00:00+00:00",
  },
  {
    id: "THD-2D8E61A7",
    customerId: "irfan-siddiqui",
    customerName: "Irfan Siddiqui",
    accountId: "AC-91002",
    kind: "legal",
    reason: "Section 138 notice issued — statutory notices only",
    source: "regulator",
    interactionId: null,
    slaDueAt: "2026-09-01T09:00:00+00:00",
    startsAt: "2026-08-12T10:30:00+00:00",
    expiresAt: null,
    releasedAt: null,
    releasedReason: null,
    placedBy: "Legal desk",
    specialist: "Rohit Desai",
    active: true,
    createdAt: "2026-08-12T10:30:00+00:00",
  },
  {
    id: "THD-6E03AA92",
    customerId: "neha-kapoor",
    customerName: "Neha Kapoor",
    accountId: "AC-90112",
    kind: "complaint",
    reason: "Escalated over call frequency — nodal officer reviewing",
    source: "manual",
    interactionId: "INT-87004",
    slaDueAt: "2026-08-14T09:00:00+00:00",
    startsAt: "2026-08-05T07:20:00+00:00",
    expiresAt: null,
    releasedAt: "2026-08-15T12:05:00+00:00",
    releasedReason: "Nodal officer closed the complaint, borrower agreed to WhatsApp only",
    placedBy: "Anand Krishnan",
    specialist: "Rohit Desai",
    active: false,
    createdAt: "2026-08-05T07:20:00+00:00",
  },
];

const mockCases: TreatmentCase[] = [
  {
    id: "bounce:MND-55120",
    customerId: "arjun-nair",
    customerName: "Arjun Nair",
    accountId: "AC-95826",
    trigger: "bounce",
    triggerRef: "MND-55120",
    decisions: 6,
    attempts: 3,
    ladder: ["sms", "whatsapp", "voice_bot"],
    lastAction: "human_call",
    lastOutcome: null,
    lastSuppression: "shadow_mode",
    rationale:
      "mandate bounced 4 days ago, 23 DPD, ₹6,446 at stake. Human call at 11:00: 68% chance of reaching them, 21% of curing if reached, ₹18.40 to try — net ₹94.",
    lastDecidedAt: "2026-08-22T05:31:08.221410+00:00",
    lastAttemptAt: "2026-08-21T13:02:44.100022+00:00",
  },
  {
    id: "dpd_tick:2026-08-21",
    customerId: "irfan-siddiqui",
    customerName: "Irfan Siddiqui",
    accountId: "AC-91002",
    trigger: "dpd_tick",
    triggerRef: "2026-08-21",
    decisions: 4,
    attempts: 0,
    ladder: [],
    lastAction: "wait",
    lastOutcome: null,
    lastSuppression: "legal_hold",
    rationale:
      "account ageing, 78 DPD, ₹6,453 at stake. Holding — a legal hold permits statutory notices only.",
    lastDecidedAt: "2026-08-22T03:16:13.113347+00:00",
    lastAttemptAt: null,
  },
  {
    id: "broken_promise:PTP-33401",
    customerId: "neha-kapoor",
    customerName: "Neha Kapoor",
    accountId: "AC-90112",
    trigger: "broken_promise",
    triggerRef: "PTP-33401",
    decisions: 5,
    attempts: 2,
    ladder: ["whatsapp", "voice_bot"],
    lastAction: "whatsapp",
    lastOutcome: "ptp",
    lastSuppression: null,
    rationale:
      "promise broken 2 days ago, 61 DPD, ₹1,600 at stake. WhatsApp at 18:00: 55% chance of reaching them, 6% of curing if reached, ₹0.42 to try — net ₹14. Timed for the first moment income usually lands.",
    lastDecidedAt: "2026-08-22T04:48:52.913004+00:00",
    lastAttemptAt: "2026-08-22T12:30:00.000000+00:00",
  },
  {
    id: "dpd_tick:2026-08-20",
    customerId: "vikram-joshi",
    customerName: "Vikram Joshi",
    accountId: "AC-92551",
    trigger: "dpd_tick",
    triggerRef: "2026-08-20",
    decisions: 8,
    attempts: 5,
    ladder: ["sms", "whatsapp", "voice_bot", "human_call", "field_visit"],
    lastAction: "wait",
    lastOutcome: null,
    lastSuppression: "daily_cap_reached",
    rationale:
      "account ageing, 104 DPD, ₹41,220 at stake. Holding — 3 of 3 permitted contacts already used today.",
    lastDecidedAt: "2026-08-22T02:10:41.775190+00:00",
    lastAttemptAt: "2026-08-21T09:15:00.000000+00:00",
  },
  {
    id: "bounce:MND-55488",
    customerId: "priya-sharma",
    customerName: "Priya Sharma",
    accountId: "AC-90881",
    trigger: "bounce",
    triggerRef: "MND-55488",
    decisions: 3,
    attempts: 1,
    ladder: ["whatsapp"],
    lastAction: "wait",
    lastOutcome: null,
    lastSuppression: "hardship_hold",
    rationale:
      "mandate bounced 6 days ago, 37 DPD, ₹12,940 at stake. Holding — a hardship hold stops outreach entirely.",
    lastDecidedAt: "2026-08-21T22:04:19.660881+00:00",
    lastAttemptAt: "2026-08-20T10:00:00.000000+00:00",
  },
  {
    id: "self_cure_window:2026-08-19",
    customerId: "sanjay-gupta",
    customerName: "Sanjay Gupta",
    accountId: "AC-93877",
    trigger: "self_cure_window",
    triggerRef: "2026-08-19",
    decisions: 2,
    attempts: 1,
    ladder: ["self_service_plan"],
    lastAction: "self_service_plan",
    lastOutcome: "paid",
    lastSuppression: null,
    rationale:
      "inside the self-cure window, 11 DPD, ₹3,180 at stake. Offering a self-service plan link: cheapest action that clears the balance without an agent.",
    lastDecidedAt: "2026-08-20T06:22:37.402118+00:00",
    lastAttemptAt: "2026-08-20T06:25:00.000000+00:00",
  },
];

const mockNext: TreatmentNext = {
  action: "whatsapp",
  actionLabel: "WhatsApp",
  channel: "whatsapp",
  at: "2026-08-23T12:30:00+00:00",
  expectedValueInr: 14.22,
  suppressed: true,
  reason: "shadow_mode",
  reasonText: "the engine is in shadow mode and enacts nothing",
  rationale:
    "mandate bounced 4 days ago, 23 DPD, ₹6,446 at stake. WhatsApp at 18:00: 55% chance of reaching them, 6% of curing if reached, ₹0.42 to try — net ₹14. Timed for the first moment income usually lands.",
  decisionId: "TD-4B18C0EA7731",
  propensity: 0.42,
  policyVersion: 1,
  mode: "shadow",
  variant: "policy",
  latencyMs: 173,
  alternatives: [
    {
      action: "voice_bot",
      channel: "voice",
      at: "2026-08-23T13:00:00+00:00",
      expectedValue: 11.08,
      pReach: 0.48,
      pResolve: 0.09,
      cost: 4.2,
      reasonCodes: ["lower_net_value"],
      components: { reach: 0.48, resolve: 0.09, exposure: 6446 },
    },
    {
      action: "human_call",
      channel: "voice",
      at: "2026-08-23T11:00:00+00:00",
      expectedValue: 9.31,
      pReach: 0.68,
      pResolve: 0.21,
      cost: 18.4,
      reasonCodes: ["agent_minutes_priced"],
      components: { reach: 0.68, resolve: 0.21, exposure: 6446 },
    },
  ],
  excluded: {
    field_visit: "exposure_below_threshold",
    legal_notice: "bucket_disallows_action",
    represent_mandate: "no_open_mandate",
  },
};

// ---------------------------------------------------------------------------
// Fetchers — one per endpoint, each with its mock branch.
// ---------------------------------------------------------------------------

export async function fetchTreatmentNext(
  customerId: string,
  accountId?: string | null,
  trigger = "manual",
): Promise<TreatmentNext> {
  if (USE_MOCK) return mockDelay(mockNext);
  const params = new URLSearchParams({ customerId, trigger });
  if (accountId) params.set("accountId", accountId);
  return apiGet<TreatmentNext>(`/treatment/next?${params.toString()}`);
}

export async function fetchTreatmentInsights(days = 14): Promise<TreatmentInsights> {
  if (USE_MOCK) return mockDelay({ ...mockInsights, windowDays: days });
  return apiGet<TreatmentInsights>(`/treatment/insights?days=${days}`);
}

export async function fetchTreatmentMetrics(
  days = 28,
  includeSimulated = false,
): Promise<TreatmentMetrics> {
  if (USE_MOCK) return mockDelay({ ...mockMetrics, windowDays: days });
  return apiGet<TreatmentMetrics>(
    `/treatment/metrics?days=${days}&includeSimulated=${includeSimulated}`,
  );
}

export async function fetchTreatmentModelHealth(
  days = 14,
  includeSimulated = false,
): Promise<TreatmentModelHealth> {
  if (USE_MOCK) return mockDelay({ ...mockModelHealth, windowDays: days });
  return apiGet<TreatmentModelHealth>(
    `/treatment/model-health?days=${days}&includeSimulated=${includeSimulated}`,
  );
}

export async function fetchTreatmentModels(
  target?: string | null,
  limit = 50,
): Promise<TreatmentModels> {
  if (USE_MOCK) {
    return mockDelay(
      target
        ? { ...mockModels, history: mockModels.history.filter((m) => m.target === target) }
        : mockModels,
    );
  }
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
  if (USE_MOCK) {
    let rows = mockHolds;
    if (customerId) rows = rows.filter((h) => h.customerId === customerId);
    if (activeOnly) rows = rows.filter((h) => h.active);
    return mockDelay(rows);
  }
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
  if (USE_MOCK) {
    const existing = mockHolds.find(
      (h) => h.active && h.customerId === input.customerId && h.kind === input.kind,
    );
    if (existing) return mockDelay(existing);
    const now = new Date().toISOString();
    const hold: TreatmentHold = {
      id: `THD-${Math.random().toString(16).slice(2, 10).toUpperCase()}`,
      customerId: input.customerId,
      customerName: input.customerId,
      accountId: input.accountId ?? null,
      kind: input.kind,
      reason: input.reason ?? null,
      source: input.source ?? "manual",
      interactionId: input.interactionId ?? null,
      slaDueAt: input.slaDueAt ?? null,
      startsAt: now,
      expiresAt: input.expiresAt ?? null,
      releasedAt: null,
      releasedReason: null,
      placedBy: "You",
      specialist: null,
      active: true,
      createdAt: now,
    };
    mockHolds.unshift(hold);
    return mockDelay(hold);
  }
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
  if (USE_MOCK) {
    const idx = mockHolds.findIndex((h) => h.id === holdId);
    if (idx === -1) throw new Error(`Hold ${holdId} not found`);
    const released: TreatmentHold = {
      ...mockHolds[idx],
      active: false,
      releasedAt: new Date().toISOString(),
      releasedReason: reason?.trim() || null,
    };
    mockHolds[idx] = released;
    return mockDelay(released);
  }
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
  if (USE_MOCK) {
    let rows = mockCases;
    if (customerId) rows = rows.filter((c) => c.customerId === customerId);
    if (openOnly) rows = rows.filter((c) => c.lastOutcome !== "paid" && c.lastOutcome !== "ptp");
    return mockDelay(rows);
  }
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
    staleTime: 15_000,
  });
}

export function useTreatmentCases(query: CaseQuery = {}) {
  const { customerId = null, openOnly = true, limit, offset } = query;
  return useQuery({
    queryKey: ["treatment-cases", customerId, openOnly, limit ?? null, offset ?? null],
    queryFn: () => fetchTreatmentCases({ customerId, openOnly, limit, offset }),
    staleTime: 15_000,
  });
}

export function useCreateTreatmentHold() {
  const qc = useQueryClient();
  return useMutation({
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
