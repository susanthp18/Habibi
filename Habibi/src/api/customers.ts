// -----------------------------------------------------------------------------
// Customer 360 — data access seam.
//   fetchCustomers()   → list rows for the index screen  (GET /customers)
//   fetchCustomer(id)  → full unified record for detail  (GET /customers/:id)
// The detail route consumes fetchCustomer via its router loader; the index
// route consumes fetchCustomers via the useCustomers() hook.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type {
  Customer,
  CustomerNote,
  Dispute,
  DocumentRequest,
  Interaction,
  Promise as PtpPromise,
} from "@/api/types/customer360";
import { customers, getCustomer } from "@/data/customer360-seed";
import { mockDisputeSla } from "@/data/dispute-sla";
import type { DisputeType } from "@/api/types/disputes";
import { deriveCustomerInsights, type CustomerInsights } from "@/lib/customerInsights";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

export async function fetchCustomers(): Promise<Customer[]> {
  if (USE_MOCK) return mockDelay(customers);
  return apiGet<Customer[]>("/customers");
}

export async function fetchCustomer(id: string): Promise<Customer | undefined> {
  if (USE_MOCK) return mockDelay(getCustomer(id));
  return apiGet<Customer | undefined>(`/customers/${id}`);
}

export async function fetchCustomerInsights(
  id: string,
  customer?: Customer,
): Promise<CustomerInsights> {
  if (USE_MOCK) {
    const c = customer ?? getCustomer(id);
    if (!c) throw new Error("Customer not found");
    return mockDelay(deriveCustomerInsights(c));
  }
  // No offline derivation on the API path. The fallback rendered a client-side
  // guess as the engine's next best action, with an Offer chip a human could
  // capture, whenever the server failed -- a 500 looked like a recommendation.
  // The screen renders the failure (QueryErrorBanner) and no action instead.
  return apiGet<CustomerInsights>(`/customers/${id}/insights`);
}

export async function addCustomerNote(
  customerId: string,
  text: string,
  pinned = false,
): Promise<CustomerNote | null> {
  if (USE_MOCK) {
    return mockDelay({
      id: `n-${Date.now()}`,
      author: "You",
      at: new Date().toISOString(),
      text,
      pinned,
    } satisfies CustomerNote);
  }
  const updated = await apiPost<Customer>(`/customers/${customerId}/notes`, { text, pinned });
  return updated.notes?.[0] ?? null;
}

export async function createPromise(
  customer: Customer,
  input: { amount: number; date: string; channel: string; notes: string },
): Promise<PtpPromise> {
  if (USE_MOCK) {
    return {
      id: `p-${Date.now()}`,
      amount: input.amount,
      promisedDate: new Date(input.date).toISOString(),
      createdAt: new Date().toISOString(),
      channel: input.channel as PtpPromise["channel"],
      handler: "You",
      status: "upcoming",
      reminderStatus: "queued",
    };
  }
  return apiPost<PtpPromise>("/promises", {
    customerId: customer.id,
    accountId: customer.accountId,
    amount: input.amount,
    promisedDate: new Date(input.date).toISOString(),
    channel: input.channel,
  });
}

export async function createDispute(
  customer: Customer,
  input: { type: DisputeType; amount: number; notes: string },
): Promise<Dispute> {
  if (USE_MOCK) {
    // Same 48h window the server gives a freshly raised dispute, run through
    // the same rule — so the mock's new row reads like a live one.
    const filedAt = new Date().toISOString();
    return {
      id: `D-${Math.floor(1000 + Math.random() * 9000)}`,
      type: input.type,
      amount: input.amount,
      transcriptSnippet: input.notes ? `"${input.notes}"` : "(no snippet)",
      status: "new",
      ...mockDisputeSla({
        capturedAt: filedAt,
        slaDueAt: new Date(Date.parse(filedAt) + 48 * 3_600_000).toISOString(),
        status: "new",
      }),
      filedAt,
      assignee: "You",
    };
  }
  return apiPost<Dispute>("/disputes", {
    customerId: customer.id,
    accountId: customer.accountId,
    type: input.type,
    amount: input.amount,
    transcriptSnippet: input.notes,
  });
}

export async function createDocumentRequest(
  customer: Customer,
  input: { docType: string; delivery: "email" | "whatsapp" },
): Promise<DocumentRequest> {
  if (USE_MOCK) {
    return {
      id: `doc-${Date.now()}`,
      type: input.docType,
      requestedVia: "voice",
      requestedAt: new Date().toISOString(),
      deliveryChannel: input.delivery,
      status: "generating",
    };
  }
  return apiPost<DocumentRequest>("/document-requests", {
    customerId: customer.id,
    accountId: customer.accountId,
    docType: input.docType,
    deliveryChannel: input.delivery,
  });
}

export async function logInteraction(
  customer: Customer,
  input: { disposition: string; notes: string },
): Promise<Interaction> {
  if (USE_MOCK) {
    return {
      id: `i-${Date.now()}`,
      channel: "voice",
      handler: { kind: "human", name: "You" },
      startedAt: new Date().toISOString(),
      duration: "3m 20s",
      disposition: input.disposition,
      sentiment: "neutral",
      sentimentDelta: "flat",
      summary: input.notes || "Logged call - no notes.",
      intents: {
        queryResolved: input.disposition === "Query resolved",
        ptpCaptured: input.disposition === "PTP captured",
      },
    };
  }
  // POST /interactions returns CallResponse — startedAt/disposition/summary are str | None.
  const call = await apiPost<{
    id: string;
    channel: Interaction["channel"];
    startedAt: string | null;
    disposition: string | null;
    summary: string | null;
    handledBy?: { agent?: string | null } | null;
  }>("/interactions", {
    customerId: customer.id,
    accountId: customer.accountId,
    channel: "voice",
    direction: "outbound",
    handlerKind: "human",
    disposition: input.disposition,
    summary: input.notes || "Logged call - no notes.",
    transcript: [{ speaker: "agent", text: input.notes || input.disposition, atSec: 0 }],
  });
  return {
    id: call.id,
    channel: call.channel,
    handler: { kind: "human", name: call.handledBy?.agent ?? "You" },
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
