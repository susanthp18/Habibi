export type SigningAlgo = "HMAC-SHA256" | "Ed25519";
export type EndpointStatus = "active" | "paused" | "broken";
export type DeliveryStatus = "success" | "client_err" | "server_err" | "pending";
export type TargetSystem = "Core Banking" | "CRM" | "Data Lake" | "Custom";

export type EventCategory = "Calls" | "Promises" | "Disputes" | "Payments" | "Consent" | "Bot";

export type EventKey =
  | "call.started"
  | "call.completed"
  | "call.summary.ready"
  | "call.escalated"
  | "promise.created"
  | "promise.kept"
  | "promise.broken"
  | "dispute.raised"
  | "dispute.resolved"
  | "payment.updated"
  | "payment.reversed"
  | "consent.dnd.updated"
  | "consent.opted_out"
  | "bot.handoff"
  | "bot.compliance.flag";

export type EventDef = {
  key: EventKey;
  category: EventCategory;
  description: string;
  sample: Record<string, unknown>;
};

export type RetryPolicy = {
  attempts: number;
  backoff: "linear" | "exponential";
  maxAgeHours: number;
};

export type Endpoint = {
  id: string;
  name: string;
  url: string;
  target: TargetSystem;
  status: EndpointStatus;
  events: EventKey[];
  algo: SigningAlgo;
  secret: string;
  retry: RetryPolicy;
  headers: { key: string; value: string }[];
  createdAt: number;
};

export type Delivery = {
  id: string;
  endpointId: string;
  event: EventKey;
  status: DeliveryStatus;
  httpStatus: number;
  latencyMs: number;
  attempt: number;
  maxAttempts: number;
  at: number;
  payload: Record<string, unknown>;
  responseBody?: string;
  /**
   * "simulated" rows come from the Integrations test-fire button, which does no
   * egress. Optional because rows written before the backend had a
   * delivery_mode column have no opinion; those default to "live".
   */
  mode?: "live" | "simulated";
};

const now = Date.now();
const hoursAgo = (h: number) => now - h * 3_600_000;
const minsAgo = (m: number) => now - m * 60_000;

/* ---------- Event catalog ---------- */
export const EVENT_CATALOG: EventDef[] = [
  {
    key: "call.started",
    category: "Calls",
    description: "Fired when a caller is connected to the voice bot.",
    sample: {
      call_id: "CALL-88213",
      from: "+91-9XXXXXX210",
      to: "1800-266-4332",
      started_at: "2026-07-21T09:14:22Z",
      channel: "voice",
      tenant: "hdfc.retail",
    },
  },
  {
    key: "call.completed",
    category: "Calls",
    description: "Emitted at hangup with duration, disposition and AHT.",
    sample: {
      call_id: "CALL-88213",
      duration_s: 187,
      disposition: "resolved",
      aht_bucket: "under_3m",
      agent: "bot",
      handoff: false,
    },
  },
  {
    key: "call.summary.ready",
    category: "Calls",
    description: "Structured summary + action items ready for CRM writeback.",
    sample: {
      call_id: "CALL-88213",
      summary: "Customer requested EMI waiver; declined; offered top-up.",
      action_items: ["send_statement"],
      sentiment: "neutral",
    },
  },
  {
    key: "call.escalated",
    category: "Calls",
    description: "Bot triggered a human handoff.",
    sample: {
      call_id: "CALL-88213",
      reason: "high_anger",
      queue: "collections_l2",
      escalated_at: "2026-07-21T09:16:04Z",
    },
  },
  {
    key: "promise.created",
    category: "Promises",
    description: "Customer committed to a Promise-to-Pay.",
    sample: {
      ptp_id: "PTP-5521",
      customer_id: "CUS-778213",
      amount: 12500,
      due_date: "2026-07-28",
      source: "bot",
    },
  },
  {
    key: "promise.kept",
    category: "Promises",
    description: "PTP fulfilled on/before due date.",
    sample: { ptp_id: "PTP-5521", paid_at: "2026-07-27T11:02:08Z", amount: 12500 },
  },
  {
    key: "promise.broken",
    category: "Promises",
    description: "PTP breach detected after due date.",
    sample: { ptp_id: "PTP-5521", broken_at: "2026-07-29T00:00:00Z", followup_queue: "recoveries" },
  },
  {
    key: "dispute.raised",
    category: "Disputes",
    description: "New dispute recorded from a call.",
    sample: {
      dispute_id: "DSP-3390",
      customer_id: "CUS-778213",
      type: "late_fee",
      severity: "medium",
    },
  },
  {
    key: "dispute.resolved",
    category: "Disputes",
    description: "Dispute closed with outcome.",
    sample: { dispute_id: "DSP-3390", outcome: "waived", amount_waived: 350 },
  },
  {
    key: "payment.updated",
    category: "Payments",
    description: "Ledger updated from Core Banking sync.",
    sample: { account_id: "LN-99812", event: "auto_debit", amount: 8320, balance: 42180 },
  },
  {
    key: "payment.reversed",
    category: "Payments",
    description: "Payment reversed / bounced.",
    sample: {
      account_id: "LN-99812",
      ref: "NEFT-7712",
      amount: 8320,
      reason: "insufficient_funds",
    },
  },
  {
    key: "consent.dnd.updated",
    category: "Consent",
    description: "DND window changed for a customer.",
    sample: {
      customer_id: "CUS-778213",
      channel: "voice",
      window: "21:00-08:00 IST",
      effective: "2026-07-21T09:16:00Z",
    },
  },
  {
    key: "consent.opted_out",
    category: "Consent",
    description: "Customer opted out of a channel entirely.",
    sample: { customer_id: "CUS-778213", channel: "sms" },
  },
  {
    key: "bot.handoff",
    category: "Bot",
    description: "Bot handed the call to a human queue.",
    sample: {
      call_id: "CALL-88213",
      to_agent: "AG-4021",
      context_summary: "waiver dispute, anger 0.82",
    },
  },
  {
    key: "bot.compliance.flag",
    category: "Bot",
    description: "Compliance rule tripped mid-call.",
    sample: { call_id: "CALL-88213", rule: "no_mini_miranda", severity: "high" },
  },
];

export const EVENT_INDEX: Record<EventKey, EventDef> = EVENT_CATALOG.reduce(
  (acc, e) => {
    acc[e.key] = e;
    return acc;
  },
  {} as Record<EventKey, EventDef>,
);

export const EVENT_CATEGORIES: EventCategory[] = [
  "Calls",
  "Promises",
  "Disputes",
  "Payments",
  "Consent",
  "Bot",
];

/* ---------- Endpoints ---------- */
const mkSecret = (prefix = "whsec") =>
  `${prefix}_${Math.random().toString(36).slice(2, 10)}${Math.random().toString(36).slice(2, 10)}`;

export const SEED_ENDPOINTS: Endpoint[] = [
  {
    id: "wh_finacle",
    name: "Finacle CBS · writeback",
    url: "https://cbs.internal.hdfc/api/hooks/collections",
    target: "Core Banking",
    status: "active",
    events: [
      "call.completed",
      "call.summary.ready",
      "promise.created",
      "promise.kept",
      "promise.broken",
      "payment.updated",
      "payment.reversed",
    ],
    algo: "HMAC-SHA256",
    secret: "whsec_fnc_9ab2c1d7e4",
    retry: { attempts: 6, backoff: "exponential", maxAgeHours: 24 },
    headers: [{ key: "X-Tenant", value: "hdfc.retail" }],
    createdAt: hoursAgo(72 * 30),
  },
  {
    id: "wh_los",
    name: "Loan LOS · upsell hooks",
    url: "https://los.internal.hdfc/webhooks/upsell",
    target: "Core Banking",
    status: "active",
    events: ["call.summary.ready", "bot.handoff"],
    algo: "HMAC-SHA256",
    secret: "whsec_los_772aa11bb",
    retry: { attempts: 4, backoff: "exponential", maxAgeHours: 12 },
    headers: [],
    createdAt: hoursAgo(72 * 14),
  },
  {
    id: "wh_lake",
    name: "Analytics data lake",
    url: "https://ingest.datalake.hdfc/collections/events",
    target: "Data Lake",
    status: "active",
    events: [
      "call.started",
      "call.completed",
      "call.summary.ready",
      "bot.handoff",
      "bot.compliance.flag",
      "promise.created",
      "promise.broken",
      "dispute.raised",
      "dispute.resolved",
    ],
    algo: "HMAC-SHA256",
    secret: "whsec_lake_5c8e120aa",
    retry: { attempts: 8, backoff: "linear", maxAgeHours: 48 },
    headers: [{ key: "X-Pipeline", value: "collections-v3" }],
    createdAt: hoursAgo(72 * 22),
  },
  {
    id: "wh_slack",
    name: "DebtOps Slack bridge",
    url: "https://hooks.slack.com/services/T0/B0/xxxxxxxxxxxx",
    target: "Custom",
    status: "active",
    events: ["call.escalated", "bot.compliance.flag", "promise.broken"],
    algo: "HMAC-SHA256",
    secret: "whsec_slk_a1b2c3d4e5",
    retry: { attempts: 3, backoff: "linear", maxAgeHours: 6 },
    headers: [],
    createdAt: hoursAgo(72 * 8),
  },
  {
    id: "wh_crm",
    name: "Salesforce CRM sync",
    url: "https://hdfc.my.salesforce.com/services/apexrest/collections/hook",
    target: "CRM",
    status: "broken",
    events: [
      "call.completed",
      "call.summary.ready",
      "promise.created",
      "consent.dnd.updated",
      "consent.opted_out",
      "dispute.raised",
    ],
    algo: "Ed25519",
    secret: "whsec_sfdc_e4d3c2b1a0",
    retry: { attempts: 5, backoff: "exponential", maxAgeHours: 24 },
    headers: [{ key: "Sforce-Auto-Assign", value: "TRUE" }],
    createdAt: hoursAgo(72 * 45),
  },
];

/* ---------- Deliveries ---------- */

const rand = <T>(arr: T[]) => arr[Math.floor(Math.random() * arr.length)];

function makeDelivery(
  ep: Endpoint,
  event: EventKey,
  at: number,
  forceStatus?: DeliveryStatus,
): Delivery {
  const roll = Math.random();
  let status: DeliveryStatus = forceStatus ?? "success";
  if (!forceStatus) {
    if (ep.status === "broken") status = roll < 0.85 ? "server_err" : "success";
    else if (roll > 0.94) status = "server_err";
    else if (roll > 0.9) status = "client_err";
  }
  const httpStatus =
    status === "success"
      ? 200
      : status === "client_err"
        ? 400 + Math.floor(Math.random() * 5)
        : status === "server_err"
          ? 500 + Math.floor(Math.random() * 4)
          : 0;
  const attempt =
    status === "success" ? 1 : Math.min(ep.retry.attempts, 1 + Math.floor(Math.random() * 3));
  const latencyMs =
    status === "success"
      ? 60 + Math.floor(Math.random() * 320)
      : 800 + Math.floor(Math.random() * 4200);
  return {
    id: `dlv_${Math.random().toString(36).slice(2, 10)}`,
    endpointId: ep.id,
    event,
    status,
    httpStatus,
    latencyMs,
    attempt,
    maxAttempts: ep.retry.attempts,
    at,
    payload: EVENT_INDEX[event].sample,
    responseBody:
      status === "success"
        ? `{"ok":true}`
        : status === "client_err"
          ? `{"error":"invalid_signature"}`
          : `{"error":"upstream_timeout"}`,
  };
}

function seedDeliveries(endpoints: Endpoint[]): Delivery[] {
  const rows: Delivery[] = [];
  for (const ep of endpoints) {
    const count = 6 + Math.floor(Math.random() * 6);
    for (let i = 0; i < count; i++) {
      const event = rand(ep.events);
      const at = minsAgo(Math.floor(Math.random() * 48 * 60));
      rows.push(makeDelivery(ep, event, at));
    }
  }
  return rows.sort((a, b) => b.at - a.at);
}

export const SEED_DELIVERIES: Delivery[] = seedDeliveries(SEED_ENDPOINTS);

/* ---------- Helpers ---------- */

/** The test-fire path. Every row it produces is labelled as simulated. */
export function simulateDelivery(
  ep: Endpoint,
  event: EventKey,
  payloadOverride?: Record<string, unknown>,
): Delivery {
  const base = makeDelivery(ep, event, Date.now());
  if (payloadOverride) base.payload = payloadOverride;
  base.mode = "simulated";
  return base;
}

export function rotateSecret(algo: SigningAlgo): string {
  return mkSecret(algo === "Ed25519" ? "ed25519" : "whsec");
}

// Deterministic non-crypto preview hash — labeled clearly in UI.
export function signaturePreview(secret: string, body: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0xdeadbeef;
  const s = secret + "|" + body;
  for (let i = 0; i < s.length; i++) {
    h1 = Math.imul(h1 ^ s.charCodeAt(i), 16777619) >>> 0;
    h2 = Math.imul(h2 ^ s.charCodeAt(i), 2246822519) >>> 0;
  }
  const hex = (n: number) => n.toString(16).padStart(8, "0");
  const t = Math.floor(Date.now() / 1000);
  return `t=${t}, v1=${hex(h1)}${hex(h2)}${hex((h1 ^ h2) >>> 0)}${hex((h1 + h2) >>> 0)}`;
}

export function successRate(list: Delivery[]): number {
  if (!list.length) return 100;
  const ok = list.filter((d) => d.status === "success").length;
  return Math.round((ok / list.length) * 100);
}

export function within(list: Delivery[], hours: number): Delivery[] {
  const cutoff = Date.now() - hours * 3_600_000;
  return list.filter((d) => d.at >= cutoff);
}

export function fmtRel(ts: number): string {
  const diff = Date.now() - ts;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function statusHttpBucket(code: number): DeliveryStatus {
  if (code === 0) return "pending";
  if (code >= 500) return "server_err";
  if (code >= 400) return "client_err";
  return "success";
}
