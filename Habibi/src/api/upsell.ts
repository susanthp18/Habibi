// -----------------------------------------------------------------------------
// Upsell & Leads Manager — data access seam.
//   fetchLeads()  → the lead pipeline   (GET /leads)
//   patchLead()   → stage / owner / team / offer  (PATCH /leads/:id)
//   createLead()  → manual capture      (POST /leads)
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import type {
  FollowUpChannel,
  FollowUp,
  Lead,
  LeadOffer,
  LeadSource,
  LeadStage,
  Priority,
  Team,
} from "@/api/types/upsell";
import type { Customer } from "@/api/types/customer360";
import { apiGet, apiPatch, apiPost } from "./config";
import { resolveProduct } from "./products";
import { humanNames, resolveActor, type Staff } from "./staff";
import { resolveTeam, teamNames, type Team as StaffTeam } from "./teams";
import { toast } from "sonner";

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

export function leadOwnerOptions(staff: Staff[]): string[] {
  return [...humanNames(staff), "Unassigned"];
}

export function leadTeamOptions(teams: StaffTeam[]): string[] {
  return teamNames(teams);
}

export function leadCustomerOptions(customers: Customer[]): Array<{
  id: string;
  name: string;
  accountId: string;
  tail: string;
}> {
  return customers.map((c) => ({
    id: c.id,
    name: c.name,
    accountId: c.accountId,
    tail: c.accountId.slice(-4),
  }));
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

export async function fetchLeads(query: LeadQuery = {}): Promise<Lead[]> {
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
  return apiGet<LeadMetrics>(`/leads/metrics${leadQueryString(query)}`);
}

export function useLeadMetrics(query: LeadQuery = {}) {
  return useQuery({
    queryKey: ["lead-metrics", leadQueryString(query)],
    queryFn: () => fetchLeadMetrics(query),
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
  return apiPost(`/leads/${lead.id}/revalidate?channel=${channel}`, {});
}

export async function addLeadFollowUp(
  lead: Lead,
  input: { at: string; channel: FollowUpChannel; note: string },
): Promise<{ id: string; status: string }> {
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
  });
}

// ---------- mutations ----------

/** The board, its metrics, and -- when the lead belongs to a customer -- their 360. */
export function invalidateLeadReads(qc: QueryClient, customerId?: string | null) {
  void qc.invalidateQueries({ queryKey: ["leads"] });
  void qc.invalidateQueries({ queryKey: ["lead-metrics"] });
  if (customerId) {
    void qc.invalidateQueries({ queryKey: ["customer-insights", customerId] });
    void qc.invalidateQueries({ queryKey: ["customer", customerId] });
  }
}

/** What PATCH /leads/:id accepts, as the sheet builds it. */
export type LeadPatch = Parameters<typeof patchLead>[1];

export function usePatchLead() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { lead: Lead; patch: LeadPatch }) => patchLead(v.lead, v.patch),
    onSuccess: (_r, v) => invalidateLeadReads(qc, v.lead.customerId),
  });
}

export function useAddLeadFollowUp() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: {
      lead: Lead;
      input: { at: string; channel: FollowUpChannel; note: string };
    }) => addLeadFollowUp(v.lead, v.input),
    onSuccess: (_r, v) => invalidateLeadReads(qc, v.lead.customerId),
  });
}

export function useMarkLeadFollowUpDone() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { lead: Lead; followUp: Lead["followUps"][number]; index: number }) =>
      markLeadFollowUpDone(v.lead, v.followUp, v.index),
    onSuccess: (_r, v) => invalidateLeadReads(qc, v.lead.customerId),
  });
}

/**
 * Eligibility was evaluated once, at capture. Consent and DPD move; this
 * re-checks against today's facts before the rep dials.
 */
export function useRevalidateLead() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { lead: Lead; channel: FollowUpChannel }) => revalidateLead(v.lead, v.channel),
    onSuccess: (result, v) => {
      invalidateLeadReads(qc, v.lead.customerId);
      if (result.eligible) toast.success("Still eligible");
      else toast.error(`No longer eligible — ${result.blockReason ?? "blocked"}`);
    },
  });
}

export function useCreateLead() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: createLead,
    onSuccess: (_r, input) => {
      invalidateLeadReads(qc, input.customerId);
      toast.success("Lead created in Interested");
    },
  });
}

/**
 * The offer engine's approved product becomes a lead. Both the 360 and the
 * handoff console capture from here, so both invalidate the same reads.
 */
export function useCaptureLeadFromPolicy() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: captureLeadFromPolicy,
    onSuccess: (_lead, input) => {
      invalidateLeadReads(qc, input.customerId);
      void qc.invalidateQueries({ queryKey: ["handoff"] });
    },
  });
}
