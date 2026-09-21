// -----------------------------------------------------------------------------
// Customer 360 — data access seam.
//   fetchCustomers()   → list rows for the index screen  (GET /customers)
//   fetchCustomer(id)  → full unified record for detail  (GET /customers/:id)
// The detail route consumes fetchCustomer via its router loader; the index
// route consumes fetchCustomers via the useCustomers() hook.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { PROMISE_STATUSES, REMINDER_STATUSES } from "@/api/types/promises";

import type {
  Customer,
  CustomerNote,
  CustomerDispute,
  DocumentRequest,
  Interaction,
  CustomerPromise as PtpPromise,
} from "@/api/types/customer360";
import type { DisputeType } from "@/api/types/disputes";
import type { CustomerInsights } from "@/api/types/customer-insights";
import { offerPolicySchema } from "@/lib/offer-policy";
import { authorityPolicySchema } from "@/lib/authority-policy";
import type { QueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./config";

// -----------------------------------------------------------------------------
// Wire schemas — field-for-field with backend/schemas.py. None of these routes
// set response_model_exclude_unset, so a `| None = None` field is always on
// the wire and is `.nullable()`, never `.optional()`. Zod strips keys it does
// not name, so a field left out here is a field the screen can never see:
// mirror the whole model, not the part a component reads today.
// -----------------------------------------------------------------------------

const channelSchema = z.enum(["voice", "whatsapp", "chat", "email", "sms"]);

/** ContactResponse. `allowedDays` is mock-only and never sent. */
const contactSchema = z.object({
  phonePrimary: z.string(),
  phoneAlt: z.string().nullable(),
  email: z.string(),
  address: z.string(),
  timezone: z.string(),
  language: z.string(),
  preferredWindow: z.string(),
  dnd: z.boolean(),
});

/** AccountResponse — `product` and `bucket` are plain `str` server-side. */
const accountSchema = z.object({
  product: z.string(),
  openedOn: z.string().nullable(),
  apr: z.number().nullable(),
  sanctionedAmount: z.number().nullable(),
  bucket: z.string().nullable(),
  dpd: z.number(),
  riskScore: z.number().nullable(),
});

const consentSchema = z.object({
  channel: z.enum(["call", "whatsapp", "sms", "email"]),
  optedIn: z.boolean(),
  source: z.string(),
  capturedAt: z.string().nullable(),
});

const ledgerEntrySchema = z.object({
  id: z.string(),
  date: z.string(),
  description: z.string(),
  type: z.enum(["charge", "payment", "fee", "adjustment", "waiver", "reversal"]),
  amount: z.number(),
  invoiceId: z.string().nullable(),
});

const emiRowSchema = z.object({
  id: z.string(),
  index: z.number(),
  dueDate: z.string(),
  amount: z.number(),
  paidOn: z.string().nullable(),
  paidAmount: z.number().nullable(),
  status: z.enum(["paid", "upcoming", "overdue", "partial"]),
  balanceCarried: z.number().nullable(),
});

/** InteractionResponse — startedAt / disposition / summary are `str | None`. */
const interactionSchema = z.object({
  id: z.string(),
  channel: channelSchema,
  handler: z.object({ kind: z.enum(["bot", "human"]), name: z.string() }),
  startedAt: z.string().nullable(),
  duration: z.string(),
  disposition: z.string().nullable(),
  sentiment: z.enum(["positive", "neutral", "negative"]),
  sentimentDelta: z.enum(["up", "down", "flat"]),
  summary: z.string().nullable(),
  intents: z.record(z.boolean()),
  transcript: z.array(z.string()),
});

/** PromiseResponse — the Customer-360 promise, also what POST /promises returns. */
export const ptpPromiseSchema = z.object({
  id: z.string(),
  amount: z.number(),
  promisedDate: z.string(),
  createdAt: z.string(),
  channel: channelSchema,
  handler: z.string(),
  status: z.enum(PROMISE_STATUSES),
  reminderStatus: z.enum(REMINDER_STATUSES),
  revisionCount: z.number().default(0),
  cancelReason: z.string().nullable().default(null),
});

/** DisputeResponse — also what POST /disputes returns. */
export const disputeSchema = z.object({
  id: z.string(),
  type: z.string(),
  amount: z.number().nullable(),
  transcriptSnippet: z.string(),
  status: z.enum(["new", "under_review", "awaiting_customer", "resolved", "rejected"]),
  sla: z.enum(["ok", "warn", "breach", "done"]),
  slaLabel: z.string(),
  slaMinutes: z.number(),
  filedAt: z.string(),
  assignee: z.string().nullable(),
});

/** DocumentRequestResponse — also what POST /document-requests returns. */
export const documentRequestSchema = z.object({
  id: z.string(),
  type: z.string(),
  requestedVia: channelSchema,
  requestedAt: z.string(),
  deliveryChannel: z.enum(["email", "whatsapp", "sms"]),
  status: z.enum(["requested", "generating", "sent", "failed"]),
  source: z.string().nullable(),
});

const customerNoteSchema = z.object({
  id: z.string(),
  author: z.string(),
  at: z.string(),
  text: z.string(),
  pinned: z.boolean(),
});

/** CustomerResponse — GET /customers, GET /customers/:id, POST .../notes, PATCH /consent/:id. */
export const customerSchema = z.object({
  id: z.string(),
  name: z.string(),
  accountId: z.string(),
  risk: z.enum(["critical", "high", "medium", "low"]),
  outstanding: z.number(),
  minimumDue: z.number().nullable(),
  lastContact: z.string().nullable(),
  assignedTo: z.string(),
  contact: contactSchema,
  account: accountSchema,
  consent: z.array(consentSchema),
  ledger: z.array(ledgerEntrySchema),
  emi: z.array(emiRowSchema),
  interactions: z.array(interactionSchema),
  promises: z.array(ptpPromiseSchema),
  disputes: z.array(disputeSchema),
  documents: z.array(documentRequestSchema),
  notes: z.array(customerNoteSchema),
});

/** CallResponse — POST /interactions. `handledBy` is `dict[str, str]` server-side. */
const callSchema = z.object({
  id: z.string(),
  startedAt: z.string().nullable(),
  duration: z.number(),
  channel: channelSchema,
  direction: z.string().nullable(),
  handledBy: z.record(z.string()),
  customerId: z.string(),
  customerName: z.string(),
  accountId: z.string().nullable(),
  disposition: z.string().nullable(),
  summary: z.string().nullable(),
  avgSentiment: z.number().nullable(),
});

const nbaActionSchema = z.enum([
  "ptp",
  "dispute",
  "statement",
  "call",
  "callback",
  "review",
  "offer",
  "message",
  "mandate",
  "schedule",
  "plan",
  "field",
  "legal",
  "wait",
]);

const treatmentAlternativeSchema = z.object({
  action: z.string(),
  channel: z.string().nullable(),
  at: z.string().nullable(),
  expectedValue: z.number().nullable(),
  pReach: z.number().nullable(),
  pResolve: z.number().nullable(),
  cost: z.number().nullable(),
  capacityPrice: z.number().nullable(),
  estimand: z.string().nullable(),
  reasonCodes: z.array(z.string()),
  components: z.record(z.number()),
});

const treatmentSnapshotSchema = z.object({
  action: z.string(),
  actionLabel: z.string().nullable(),
  channel: z.string().nullable(),
  at: z.string().nullable(),
  expectedValueInr: z.number().nullable(),
  suppressed: z.boolean(),
  reason: z.string().nullable(),
  reasonText: z.string().nullable(),
  rationale: z.string(),
  decisionId: z.string().nullable(),
  propensity: z.number().nullable(),
  policyVersion: z.number().nullable(),
  mode: z.string().nullable(),
  variant: z.string().nullable(),
  latencyMs: z.number().nullable(),
  alternatives: z.array(treatmentAlternativeSchema),
  excluded: z.record(z.string()),
});

/** CustomerInsightsResponse — GET /customers/:id/insights. */
const customerInsightsSchema = z.object({
  customerId: z.string(),
  summary: z.array(
    z.object({
      id: z.string(),
      text: z.string(),
      source: z.string(),
      confidence: z.enum(["high", "medium", "low"]),
    }),
  ),
  nba: z.array(
    z.object({
      id: z.string(),
      rank: z.number(),
      title: z.string(),
      reason: z.string(),
      action: nbaActionSchema,
      priority: z.enum(["high", "medium", "low"]),
      leadId: z.string().nullable(),
      source: z.string().nullable(),
      decisionId: z.string().nullable(),
      expectedValueInr: z.number().nullable(),
      scheduledAt: z.string().nullable(),
      treatmentAction: z.string().nullable(),
      advisory: z.boolean().nullable(),
    }),
  ),
  metrics: z.object({
    ptpKeepRate: z.number().nullable(),
    daysSinceContact: z.number().nullable(),
    openDisputeAmount: z.number(),
    nextEmiAmount: z.number().nullable(),
    nextEmiDate: z.string().nullable(),
    paymentStreak: z.number(),
    brokenPromiseCount: z.number(),
    activePromiseAmount: z.number(),
  }),
  activity: z.array(
    z.object({
      id: z.string(),
      kind: z.string(),
      label: z.string(),
      note: z.string().nullable(),
      at: z.string().nullable(),
      tone: z.string().nullable(),
    }),
  ),
  generatedAt: z.string(),
  offerPolicy: offerPolicySchema.nullable(),
  authorityPolicy: authorityPolicySchema.nullable(),
  treatment: treatmentSnapshotSchema.nullable(),
});

export async function fetchCustomers(): Promise<Customer[]> {
  return apiGet<Customer[]>("/customers", { schema: z.array(customerSchema) });
}

export async function fetchCustomer(id: string): Promise<Customer | undefined> {
  return apiGet<Customer | undefined>(`/customers/${id}`, { schema: customerSchema });
}

export async function fetchCustomerInsights(
  id: string,
  customer?: Customer,
): Promise<CustomerInsights> {
  // No offline derivation on the API path. The fallback rendered a client-side
  // guess as the engine's next best action, with an Offer chip a human could
  // capture, whenever the server failed -- a 500 looked like a recommendation.
  // The screen renders the failure (QueryErrorBanner) and no action instead.
  return apiGet<CustomerInsights>(`/customers/${id}/insights`, {
    schema: customerInsightsSchema,
  });
}

export async function addCustomerNote(
  customerId: string,
  text: string,
  pinned = false,
): Promise<CustomerNote | null> {
  const updated = await apiPost<Customer>(
    `/customers/${customerId}/notes`,
    { text, pinned },
    { schema: customerSchema },
  );
  return updated.notes?.[0] ?? null;
}

export async function createDocumentRequest(
  customer: Customer,
  input: { docType: string; delivery: "email" | "whatsapp" },
): Promise<DocumentRequest> {
  return apiPost<DocumentRequest>(
    "/document-requests",
    {
      customerId: customer.id,
      accountId: customer.accountId,
      docType: input.docType,
      deliveryChannel: input.delivery,
    },
    { schema: documentRequestSchema },
  );
}

export async function logInteraction(
  customer: Customer,
  input: { disposition: string; notes: string },
): Promise<Interaction> {
  // POST /interactions returns CallResponse — startedAt/disposition/summary are str | None.
  const call = await apiPost(
    "/interactions",
    {
      customerId: customer.id,
      accountId: customer.accountId,
      channel: "voice",
      direction: "outbound",
      handlerKind: "human",
      disposition: input.disposition,
      summary: input.notes || "Logged call - no notes.",
      transcript: [{ speaker: "agent", text: input.notes || input.disposition, atSec: 0 }],
    },
    { schema: callSchema },
  );
  return {
    id: call.id,
    channel: call.channel,
    handler: { kind: "human", name: call.handledBy.agent ?? "You" },
    startedAt: call.startedAt,
    duration: "0m 00s",
    disposition: call.disposition,
    sentiment: "neutral",
    sentimentDelta: "flat",
    summary: call.summary,
    intents: {
      queryResolved: input.disposition === "Query resolved",
      ptpCaptured: input.disposition === "PTP captured",
    },
  };
}

export function useCustomers() {
  return useQuery({
    queryKey: ["customers"],
    queryFn: fetchCustomers,
    staleTime: 30_000,
  });
}

// ---------- mutations ----------

/** Every 360 read the write can move. */
export function invalidateCustomer(qc: QueryClient, customerId: string) {
  void qc.invalidateQueries({ queryKey: ["customers"] });
  void qc.invalidateQueries({ queryKey: ["customer", customerId] });
  void qc.invalidateQueries({ queryKey: ["customer-insights", customerId] });
}

export function useCreateDocumentRequest(customer: Customer) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (payload: { docType: string; delivery: "email" | "whatsapp" }) =>
      createDocumentRequest(customer, payload),
    onSuccess: () => {
      invalidateCustomer(qc, customer.id);
      void qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useLogInteraction(customer: Customer) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (payload: { disposition: string; notes: string }) =>
      logInteraction(customer, payload),
    onSuccess: () => invalidateCustomer(qc, customer.id),
  });
}

/** The returned note is put straight into the cached customer; a null answer refetches. */
export function useAddCustomerNote(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (text: string) => addCustomerNote(customerId, text),
    onSuccess: (note) => {
      if (note) {
        qc.setQueryData<Customer>(["customer", customerId], (c) =>
          c ? { ...c, notes: [note, ...c.notes] } : c,
        );
        void qc.invalidateQueries({ queryKey: ["customer-insights", customerId] });
      } else {
        invalidateCustomer(qc, customerId);
      }
    },
  });
}

export type OutreachChannel = "whatsapp" | "sms";

export async function sendCustomerOutreach(
  customerId: string,
  payload: { channel: OutreachChannel; text: string; idempotencyKey: string },
) {
  return apiPost(`/customers/${encodeURIComponent(customerId)}/outreach`, {
    channel: payload.channel,
    text: payload.text,
  }, { headers: { "Idempotency-Key": payload.idempotencyKey } });
}

export function useSendCustomerOutreach() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: {
      customerId: string;
      channel: OutreachChannel;
      text: string;
      idempotencyKey: string;
    }) =>
      sendCustomerOutreach(input.customerId, {
        channel: input.channel,
        text: input.text,
        idempotencyKey: input.idempotencyKey,
      }),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      invalidateCustomer(qc, vars.customerId);
    },
  });
}
