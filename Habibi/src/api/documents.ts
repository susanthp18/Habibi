// -----------------------------------------------------------------------------
// Document Fulfilment Desk — data access seam.
//   fetchDocuments() → queue list  (GET /document-requests)
//   create / assign / channel / template / reopen → Phase 3A writes
//
// PayInt renders and sends no documents yet. A request becomes "sent" only
// through recordManualSend (POST .../delivery-attempts): a person confirming
// they are sending it themselves. The screen shape is richer than the write
// response, so callers invalidate + refetch. Assignees resolve through /staff.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  DocChannel,
  DocRequest,
  DocStatus,
  DocType,
  NewRequestInput,
} from "@/api/types/documents";
import { apiGet, apiPatch, apiPost } from "./config";
import { currentActor } from "./me";
import { UNASSIGNED, humanNames, resolveActor, type Staff } from "./staff";
import { toast } from "sonner";

export function documentAssigneeOptions(staff: Staff[]): string[] {
  return humanNames(staff);
}

/** ``id`` reads that one record whatever page it is on (a deep link). */
export async function fetchDocuments(id?: string): Promise<DocRequest[]> {
  return apiGet<DocRequest[]>(
    id ? `/document-requests?id=${encodeURIComponent(id)}` : "/document-requests",
  );
}

export function useDocuments() {
  return useQuery({ queryKey: ["documents"], queryFn: () => fetchDocuments() });
}

export async function createRequest(input: NewRequestInput): Promise<{ id: string }> {
  const me = await currentActor();
  const created = await apiPost<{ id: string }>("/document-requests", {
    customerId: input.customerId,
    docType: input.docType,
    period: input.period,
    deliveryChannel: input.channel,
    templateId: input.templateId,
    requestedVia: "agent",
    assigneeUserId: me.id,
  });
  return created;
}

export async function assignDocument(doc: DocRequest, assignee: string): Promise<void> {
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
  await apiPatch(`/document-requests/${doc.id}`, { deliveryChannel: channel });
}

export async function changeTemplate(doc: DocRequest, templateId: string): Promise<void> {
  await apiPatch(`/document-requests/${doc.id}`, { templateId });
}

/**
 * A person confirming they are sending this document themselves. The server
 * applies the contact policy and refuses (409, with the reason) when the
 * customer may not be contacted on this channel now; nothing is recorded then.
 */
export async function recordManualSend(doc: DocRequest): Promise<void> {
  await apiPost(`/document-requests/${doc.id}/delivery-attempts`, {
    status: "sent",
    provider: "manual",
  });
}

/** Reopen a failed request. Nothing is sent or queued. */
export async function retryDocument(doc: DocRequest): Promise<void> {
  await apiPatch(`/document-requests/${doc.id}`, {
    status: "requested",
    failedReason: null,
  });
}

export type { DocChannel, DocRequest, DocStatus, DocType, NewRequestInput };

// ---------- mutations ----------

export function useReassignDocumentChannel() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { doc: DocRequest; channel: DocChannel }) => reassignChannel(v.doc, v.channel),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}

export function useRetryDocument() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (doc: DocRequest) => retryDocument(doc),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Request reopened");
    },
  });
}
