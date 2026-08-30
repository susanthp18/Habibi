// -----------------------------------------------------------------------------
// Customer 360 — data access seam.
//   fetchCustomers()   → list rows for the index screen  (GET /customers)
//   fetchCustomer(id)  → full unified record for detail  (GET /customers/:id)
// The detail route consumes fetchCustomer via its router loader; the index
// route consumes fetchCustomers via the useCustomers() hook.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  customers,
  getCustomer,
  type Customer,
  type CustomerNote,
  type Dispute,
  type DocumentRequest,
  type Interaction,
  type Promise as PtpPromise,
} from "@/data/customer360-seed";
import { mockDisputeSla } from "@/data/dispute-sla";
import type { DisputeType } from "@/data/disputes-seed";
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
  try {
    return await apiGet<CustomerInsights>(`/customers/${id}/insights`);
  } catch (err) {
    // Fallback to client derivation if API unavailable.
    //
    // This catch was bare. That is why a 500 from this endpoint shipped: a
    // ResponseValidationError and an unplugged API are indistinguishable here,
    // so a broken server looked exactly like an offline one and the UI quietly
    // rendered "Recommendation unavailable" instead. The fallback is a real
    // offline path and stays; only its silence goes.
    console.error(`[insights] /customers/${id}/insights failed, deriving offline`, err);
    const c = customer ?? (await fetchCustomer(id));
    if (!c) throw new Error("Customer not found");
    return deriveCustomerInsights(c);
  }
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
  const call = await apiPost<{
    id: string;
    channel: Interaction["channel"];
    startedAt: string;
    disposition: string;
    summary: string;
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
