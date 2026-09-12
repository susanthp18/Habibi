/**
 * Domain / wire types for the webhooks surface.
 *
 * `Endpoint` and `Delivery` are the /webhook-endpoints and /webhook-deliveries
 * rows; `EventDef` is one /event-types entry.
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
  /** Masked on the list; the plaintext is `secretOnce` on create and rotate. */
  secret: string;
  secretRef: string;
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
