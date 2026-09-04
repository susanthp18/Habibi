/**
 * Domain / wire types for the webhooks surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

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
