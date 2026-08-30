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
  computeMetrics,
  createLead as createSeedLead,
  defaultFilters,
  filterLeads,
  leads,
  markFollowUpDone,
  markLost,
  markWon,
  moveStage,
  reassignTeam,
  scheduleFollowUp,
  updateOffer,
  type Filters,
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

/** Channel used for consent re-check — from how the lead was captured, not always voice. */
export function leadContactChannel(source: LeadSource | string | undefined): FollowUpChannel {
  if (source === "bot_chat") return "whatsapp";
  return "voice";
}

export function followUpChannelFromPolicy(
  channel: string | null | undefined,
  source?: LeadSource | string,
): FollowUpChannel {
  if (channel === "whatsapp" || channel === "sms" || channel === "email") return channel;
  if (channel === "chat") return "whatsapp";
  if (channel === "voice") return "voice";
  return leadContactChannel(source);
}

async function teamId(team: Team | undefined): Promise<string | undefined> {
  if (team === undefined) return undefined;
  return (await resolveTeam(team)).id;
}

/**
 * Filters the server understands. Everything the FiltersBar offers is here, so
 * the board and the KPI strip are always describing the same set of leads —
 * the strip used to be computed in the browser over whatever the first page of
 * `GET /leads` happened to contain, which is only the right answer while the
 * whole book fits in one page.
 */
export interface LeadQuery {
  q?: string;
  stage?: LeadStage;
  owner?: string;
  team?: Team;
  productId?: string;
  source?: LeadSource;
  /** Multi-select; sent comma-separated. */
  priorities?: Priority[];
  /** Multi-select; sent comma-separated. */
  sentiments?: string[];
}

function leadQueryString(query: LeadQuery = {}): string {
  const params = new URLSearchParams();
  const put = (key: string, value: string | undefined) => {
    const v = (value ?? "").trim();
    // "all" is the screen's word for unset; the server treats it the same, but
    // leaving it out keeps the query key — and so the cache entry — stable.
    if (v && v !== "all") params.set(key, v);
  };
  put("q", query.q);
  put("stage", query.stage);
  put("owner", query.owner);
  put("team", query.team);
  put("productId", query.productId);
  put("source", query.source);
  put("priority", query.priorities?.join(","));
  put("sentiment", query.sentiments?.join(","));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** LeadQuery → the seed's Filters shape, so mock mode filters identically. */
function seedFilters(query: LeadQuery): Filters {
  return {
    ...defaultFilters,
    search: query.q ?? "",
    team: (query.team ?? "all") as Filters["team"],
    owner: query.owner ?? "all",
    productId: query.productId ?? "all",
    source: (query.source ?? "all") as Filters["source"],
    sentiments: (query.sentiments ?? []) as Filters["sentiments"],
    priorities: (query.priorities ?? []) as Filters["priorities"],
    myQueue: false,
  };
}

export async function fetchLeads(query: LeadQuery = {}): Promise<Lead[]> {
  if (USE_MOCK) {
    const rows = filterLeads(leads, seedFilters(query));
    return mockDelay(query.stage ? rows.filter((l) => l.stage === query.stage) : rows);
  }
  return apiGet<Lead[]>(`/leads${leadQueryString(query)}`);
}

export interface LeadMetrics {
  total: number;
  openLeads: number;
  pipelineValue: number;
  wonWeek: number;
  wonWeekAmount: number;
  /** Null when nothing was captured in the window — not the same as 0%. */
  conversionRate: number | null;
  captured30d: number;
  won30d: number;
  /** Null when nothing has closed yet. */
  avgDaysToClose: number | null;
  perStage: Record<LeadStage, { count: number; amount: number }>;
}

export async function fetchLeadMetrics(query: LeadQuery = {}): Promise<LeadMetrics> {
  if (USE_MOCK) {
    const rows = await fetchLeads(query);
    const m = computeMetrics(rows);
    return mockDelay({
      total: rows.length,
      openLeads: m.openLeads,
      pipelineValue: m.pipelineValue,
      wonWeek: m.wonWeek,
      wonWeekAmount: m.wonWeekAmount,
      conversionRate: m.conversionRate,
      captured30d: 0,
      won30d: 0,
      avgDaysToClose: m.avgDaysToClose,
      perStage: m.perStage,
    });
  }
  return apiGet<LeadMetrics>(`/leads/metrics${leadQueryString(query)}`);
}

export function useLeadMetrics(query: LeadQuery = {}) {
  return useQuery({
    queryKey: ["lead-metrics", leadQueryString(query)],
    queryFn: () => fetchLeadMetrics(query),
    staleTime: 15_000,
  });
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
    if (patch.stage && patch.stage !== lead.stage)
      moveStage(lead.id, patch.stage, undefined, patch.lossReason);
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
  const body: Record<string, unknown> = {};
  if (patch.stage !== undefined) body.stage = patch.stage;
  if (patch.offer?.productId !== undefined) {
    body.productId = patch.offer.productId;
    body.channel = leadContactChannel(lead.source);
  }
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
  channel: FollowUpChannel = leadContactChannel(lead.source),
): Promise<{ leadId: string; eligible: boolean; blockReason: string | null }> {
  if (USE_MOCK) {
    return mockDelay({ leadId: lead.id, eligible: true, blockReason: null });
  }
  return apiPost(`/leads/${lead.id}/revalidate?channel=${channel}`, {});
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

export async function markLeadFollowUpDone(
  lead: Lead,
  followUp: FollowUp,
  index: number,
): Promise<{ id: string; status: string }> {
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
    channel: leadContactChannel(input.source),
  });
}

/** Capture from a living offer policy (Handoff / 360) — not a freelance product pick. */
export async function captureLeadFromPolicy(input: {
  customerId: string;
  productId: string;
  indicativeAmount?: number | null;
  source?: LeadSource;
  decisionId?: string | null;
  interactionId?: string | null;
  channel?: string | null;
  note?: string | null;
}): Promise<Lead> {
  const source = input.source ?? "agent";
  const amount = input.indicativeAmount ?? 0;
  if (USE_MOCK) {
    return mockDelay(
      createSeedLead({
        customerId: input.customerId,
        productId: input.productId,
        indicativeAmount: amount,
        team: "Retail Sales",
        owner: "Unassigned",
        source,
        priority: "normal",
        note: input.note || "Captured from offer policy",
      }),
    );
  }
  const product = await resolveProduct(input.productId);
  return apiPost<Lead>("/leads", {
    customerId: input.customerId,
    productId: input.productId,
    source,
    transcriptSnippet: input.note || undefined,
    offerAmount: input.indicativeAmount ?? undefined,
    offerRoi: product?.indicativeROI,
    estimatedValue: input.indicativeAmount ?? undefined,
    channel: followUpChannelFromPolicy(input.channel, source),
    decisionId: input.decisionId || undefined,
    interactionId: input.interactionId || undefined,
  });
}

export function useLeads(query: LeadQuery = {}) {
  return useQuery({
    queryKey: ["leads", leadQueryString(query)],
    queryFn: () => fetchLeads(query),
    staleTime: 15_000,
  });
}
