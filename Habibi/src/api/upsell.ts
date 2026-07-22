// -----------------------------------------------------------------------------
// Upsell & Leads Manager — data access seam (read side).
//   fetchLeads() → the lead pipeline  (GET /leads)
//
// NOTE: stage moves / create / assign currently mutate the in-memory seed
// (see moveStage, createLead, etc. in upsell-seed). Those map to POST/PATCH
// endpoints in Phase 2 and should become useMutation calls then. Phase 1 only
// seams the read so the screen loads its list through the data layer.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  assign,
  createLead as createSeedLead,
  leads,
  markFollowUpDone,
  markLost,
  markWon,
  moveStage,
  productMap,
  reassignTeam,
  scheduleFollowUp,
  updateOffer,
  type FollowUpChannel,
  type FollowUp,
  type Lead,
  type LeadOffer,
  type LeadSource,
  type LeadStage,
  type Priority,
  type Team,
} from "@/data/upsell-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { resolveActor } from "./staff";
import { resolveTeam } from "./teams";

/** Resolve an owner name to a real user id, or undefined for "Unassigned". */
async function ownerUserId(owner: string | undefined): Promise<string | undefined> {
  if (owner === undefined || owner === "Unassigned") return undefined;
  const actor = await resolveActor(owner);
  if (actor.kind !== "human") {
    throw new Error(`${owner} is a bot — leads are owned by people`);
  }
  return actor.id;
}

async function teamId(team: Team | undefined): Promise<string | undefined> {
  if (team === undefined) return undefined;
  return (await resolveTeam(team)).id;
}

export async function fetchLeads(): Promise<Lead[]> {
  if (USE_MOCK) return mockDelay(leads);
  return apiGet<Lead[]>("/leads");
}

export async function patchLead(
  lead: Lead,
  patch: {
    stage?: LeadStage;
    owner?: string;
    team?: Team;
    offer?: Partial<LeadOffer>;
    wonAmount?: number;
    lossReason?: string;
  },
): Promise<Lead> {
  if (USE_MOCK) {
    if (patch.stage && patch.stage !== lead.stage) moveStage(lead.id, patch.stage, undefined, patch.lossReason);
    if (patch.owner !== undefined) assign(lead.id, patch.owner);
    if (patch.team !== undefined) reassignTeam(lead.id, patch.team);
    if (patch.offer !== undefined) updateOffer(lead.id, patch.offer);
    if (patch.wonAmount !== undefined) markWon(lead.id, patch.wonAmount);
    if (patch.lossReason !== undefined) markLost(lead.id, patch.lossReason);
    return mockDelay(leads.find((l) => l.id === lead.id) ?? lead);
  }

  return apiPatch<Lead>(`/leads/${lead.id}`, {
    stage: patch.stage,
    productId: patch.offer?.productId,
    ownerUserId: await ownerUserId(patch.owner),
    teamId: await teamId(patch.team),
    offerAmount: patch.offer?.indicativeAmount,
    offerRoi: patch.offer?.indicativeROI,
    wonAmount: patch.wonAmount,
    lossReason: patch.lossReason,
  });
}

export async function addLeadFollowUp(
  lead: Lead,
  input: { at: string; channel: FollowUpChannel; note: string },
): Promise<{ id: string; status: string }> {
  if (USE_MOCK) {
    scheduleFollowUp(lead.id, input.at, input.channel, input.note);
    return mockDelay({ id: `FU-${Date.now()}`, status: "open" });
  }

  return apiPost<{ id: string; status: string }>(`/leads/${lead.id}/followups`, {
    scheduledAt: input.at,
    channel: input.channel,
    note: input.note,
  });
}

export async function markLeadFollowUpDone(lead: Lead, followUp: FollowUp, index: number): Promise<{ id: string; status: string }> {
  if (USE_MOCK) {
    markFollowUpDone(lead.id, index);
    return mockDelay({ id: followUp.id ?? `FU-${index}`, status: "done" });
  }
  if (!followUp.id) throw new Error("Follow-up id missing");
  return apiPatch<{ id: string; status: string }>(`/followups/${followUp.id}`, { status: "done" });
}

export async function createLead(input: {
  customerId: string;
  productId: string;
  indicativeAmount: number;
  team: Team;
  owner: string;
  source: LeadSource;
  priority: Priority;
  note: string;
}): Promise<Lead> {
  if (USE_MOCK) return mockDelay(createSeedLead(input));

  const product = productMap[input.productId];
  return apiPost<Lead>("/leads", {
    customerId: input.customerId,
    productId: input.productId,
    source: input.source,
    transcriptSnippet: input.note,
    ownerUserId: await ownerUserId(input.owner),
    teamId: await teamId(input.team),
    offerAmount: input.indicativeAmount,
    offerRoi: product?.indicativeROI,
    estimatedValue: input.indicativeAmount,
    priority: input.priority,
  });
}

export function useLeads() {
  return useQuery({
    queryKey: ["leads"],
    queryFn: fetchLeads,
    staleTime: 15_000,
  });
}
