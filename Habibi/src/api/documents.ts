// -----------------------------------------------------------------------------
// Document Fulfilment Desk — data access seam.
//   fetchDocuments() → queue list  (GET /document-requests)
//   create / assign / channel / template / status transitions → Phase 3A writes
//
// Mock branch preserves the in-memory seed mutators exactly. Live branch maps
// to POST/PATCH (+ delivery-attempts on retry); the screen shape is richer than
// the write response, so callers invalidate + refetch. Assignees resolve through
// /staff (never hardcoded CURRENT_AGENT maps).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  assign as assignSeed,
  changeTemplate as changeSeedTemplate,
  createRequest as createSeedRequest,
  documents as seedDocuments,
  markFailed as markSeedFailed,
  markGenerating as markSeedGenerating,
  markSent as markSeedSent,
  reassignChannel as reassignSeedChannel,
  retry as retrySeed,
  setStatus as setSeedStatus,
  type DocChannel,
  type DocRequest,
  type DocStatus,
  type DocType,
  type NewRequestInput,
} from "@/data/documents-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { currentActor } from "./me";
import { resolveActor } from "./staff";

export const UNASSIGNED = "Unassigned";

export async function fetchDocuments(): Promise<DocRequest[]> {
  if (USE_MOCK) return mockDelay(seedDocuments);
  return apiGet<DocRequest[]>("/document-requests");
}

export function useDocuments() {
  return useQuery({ queryKey: ["documents"], queryFn: fetchDocuments, staleTime: 15_000 });
}

export async function createRequest(input: NewRequestInput): Promise<{ id: string }> {
  if (USE_MOCK) {
    const created = createSeedRequest(input);
    return { id: created.id };
  }
  const me = await currentActor();
  const created = await apiPost<{ id: string }>("/document-requests", {
    customerId: input.customerId,
    docType: input.docType,
    period: input.period,
    deliveryChannel: input.channel,
    templateId: input.templateId,
    requestedVia: "agent",
    assigneeUserId: me.id,
    // filename/mimeType optional — server derives storage_ref if a file row is created.
    filename: `${input.docType}.pdf`,
    mimeType: "application/pdf",
  });
  return created;
}

export async function assignDocument(doc: DocRequest, assignee: string): Promise<void> {
  if (USE_MOCK) {
    assignSeed(doc.id, assignee);
    return;
  }
  if (assignee === UNASSIGNED) {
    await apiPatch(`/document-requests/${doc.id}`, { assigneeUserId: null });
    return;
  }
  const actor = await resolveActor(assignee);
  if (actor.kind !== "human") {
    throw new Error(`${assignee} is a bot — document fulfilment is assigned to people`);
  }
  await apiPatch(`/document-requests/${doc.id}`, { assigneeUserId: actor.id });
}

export async function reassignChannel(doc: DocRequest, channel: DocChannel): Promise<void> {
  if (USE_MOCK) {
    reassignSeedChannel(doc.id, channel);
    return;
  }
  await apiPatch(`/document-requests/${doc.id}`, { deliveryChannel: channel });
}

export async function changeTemplate(doc: DocRequest, templateId: string): Promise<void> {
  if (USE_MOCK) {
    changeSeedTemplate(doc.id, templateId);
    return;
  }
  await apiPatch(`/document-requests/${doc.id}`, { templateId });
}

export async function setStatus(
  doc: DocRequest,
  next: DocStatus,
  extra?: Partial<Pick<DocRequest, "generatedAt" | "sentAt" | "failedReason" | "sizeKb">>,
): Promise<void> {
  if (USE_MOCK) {
    setSeedStatus(doc.id, next, extra);
    return;
  }
  await apiPatch(`/document-requests/${doc.id}`, {
    status: next,
    ...extra,
  });
}

export async function markGenerating(doc: DocRequest): Promise<void> {
  if (USE_MOCK) {
    markSeedGenerating(doc.id);
    return;
  }
  await apiPatch(`/document-requests/${doc.id}`, {
    status: "generating",
    generatedAt: new Date().toISOString(),
    failedReason: null,
  });
}

export async function markSent(doc: DocRequest): Promise<void> {
  if (USE_MOCK) {
    markSeedSent(doc.id);
    return;
  }
  const sizeKb = doc.sizeKb ?? 140 + Math.floor(Math.random() * 400);
  await apiPatch(`/document-requests/${doc.id}`, {
    status: "sent",
    sentAt: new Date().toISOString(),
    sizeKb,
    failedReason: null,
  });
}

export async function markFailed(doc: DocRequest, reason: string): Promise<void> {
  if (USE_MOCK) {
    markSeedFailed(doc.id, reason);
    return;
  }
  await apiPatch(`/document-requests/${doc.id}`, {
    status: "failed",
    failedReason: reason,
  });
}

/** Reset to requested and bump attempts via the delivery-attempts endpoint. */
export async function retryDocument(doc: DocRequest): Promise<void> {
  if (USE_MOCK) {
    retrySeed(doc.id);
    return;
  }
  await apiPatch(`/document-requests/${doc.id}`, {
    status: "requested",
    failedReason: null,
  });
  await apiPost(`/document-requests/${doc.id}/delivery-attempts`, {
    status: "queued",
    provider: "manual",
  });
}

export type { DocChannel, DocRequest, DocStatus, DocType, NewRequestInput };
