// -----------------------------------------------------------------------------
// Upsell & Leads Manager — data access seam.
//   fetchLeads()  → the lead pipeline   (GET /leads)
//   patchLead()   → stage / owner / team / offer  (PATCH /leads/:id)
//   createLead()  → manual capture      (POST /leads)
//
// In mock mode these mutate the in-memory seed; live they hit the API. The two
// paths are kept behaviourally identical on purpose — a difference between them
// is a bug that only shows up in production.
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
import { resolveProduct } from "./products";
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

/** Where a follow-up contact would happen — makes the consent re-check exact. */
const LEAD_CHANNEL = "voice" as const;

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

  // Only send what actually changed. The endpoint uses exclude_unset, so an
  // explicit null clears a column while an omitted key leaves it alone —
  // sending every field on every patch would wipe values nobody touched.
  const body: Record<string, unknown> = { channel: LEAD_CHANNEL };
  if (patch.stage !== undefined) body.stage = patch.stage;
  if (patch.offer?.productId !== undefined) body.productId = patch.offer.productId;
  if (patch.owner !== undefined) body.ownerUserId = await ownerUserId(patch.owner);
  if (patch.team !== undefined) body.teamId = await teamId(patch.team);
  if (patch.offer?.indicativeAmount !== undefined) body.offerAmount = patch.offer.indicativeAmount;
  if (patch.offer?.indicativeROI !== undefined) body.offerRoi = patch.offer.indicativeROI;
  if (patch.wonAmount !== undefined) body.wonAmount = patch.wonAmount;
  if (patch.lossReason !== undefined) body.lossReason = patch.lossReason;

  return apiPatch<Lead>(`/leads/${lead.id}`, body);
}

/**
 * Re-check a lead's eligibility against today's consent and account facts.
 *
 * Eligibility was evaluated once, at capture, and never again — so a customer
 * who opted out afterwards kept an actionable lead with a green badge on it.
 */
export async function revalidateLead(
  lead: Lead,
): Promise<{ leadId: string; eligible: boolean; blockReason: string | null }> {
  if (USE_MOCK) {
    return mockDelay({ leadId: lead.id, eligible: true, blockReason: null });
  }
  return apiPost(`/leads/${lead.id}/revalidate?channel=${LEAD_CHANNEL}`, {});
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

  // ROI comes from the catalog the server serves, not a hardcoded copy of it —
  // otherwise the ROI stored on the lead can disagree with the product.
  const product = await resolveProduct(input.productId);
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
    channel: LEAD_CHANNEL,
  });
}

export function useLeads() {
  return useQuery({
    queryKey: ["leads"],
    queryFn: fetchLeads,
    staleTime: 15_000,
  });
}
