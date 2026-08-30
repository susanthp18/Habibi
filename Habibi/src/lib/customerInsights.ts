import type { Customer } from "@/data/customer360-seed";
import { emptyOfferPolicy, fmtOfferAmount, type OfferPolicy } from "@/lib/offer-policy";

export type NbaActionKind =
  | "ptp"
  | "dispute"
  | "statement"
  | "call"
  | "callback"
  | "review"
  | "offer"
  // Spoken by the decision engine. The card used to have its own contact
  // ladder — "DND, so WhatsApp", "outside the window, so schedule a callback",
  // "over 30 DPD, so call" — written twice, once here and once in Python, and
  // kept in step by hand. The engine decides those against the real consent
  // record, the real calling window and the real frequency budget, so they are
  // gone from both copies and these are what it says instead.
  | "message"
  | "mandate"
  | "schedule"
  | "plan"
  | "field"
  | "legal"
  | "wait";

export type InsightBullet = {
  id: string;
  text: string;
  source: string;
  confidence: "high" | "medium" | "low";
};

export type NbaItem = {
  id: string;
  rank: number;
  title: string;
  reason: string;
  action: NbaActionKind;
  priority: "high" | "medium" | "low";
  leadId?: string | null;
  /** Present on the engine's row. A rupee figure a collections head can argue
   *  with, rather than a dimensionless priority nobody can. */
  expectedValueInr?: number | null;
  scheduledAt?: string | null;
  decisionId?: string | null;
  treatmentAction?: string | null;
  source?: "treatment_engine" | null;
  /** The engine decided but is not acting — shadow mode. Labelled rather than
   *  hidden, so nobody reads a shadow recommendation as queued work. */
  advisory?: boolean;
};

export type BehaviorMetrics = {
  ptpKeepRate: number | null;
  daysSinceContact: number | null;
  openDisputeAmount: number;
  nextEmiAmount: number | null;
  nextEmiDate: string | null;
  paymentStreak: number;
  brokenPromiseCount: number;
  activePromiseAmount: number;
};

export type ActivityPreviewItem = {
  id: string;
  kind: string;
  label: string;
  note?: string | null;
  at: string;
  tone?: string | null;
};

/** One ranked action the engine considered but did not pick.
 *  Mirrors agent_core/treatment/scoring.py :: ScoredAction.to_log(). Note the
 *  key is `expectedValue` here and `expectedValueInr` on the chosen action —
 *  the producer spells them differently, so this does too. */
export type TreatmentAlternative = {
  action: string;
  channel?: string | null;
  at?: string | null;
  expectedValue?: number | null;
  pReach?: number | null;
  pResolve?: number | null;
  cost?: number | null;
  reasonCodes?: string[];
  components?: Record<string, number>;
};

/** The engine's full payload, not just the row rendered as an NBA. The excluded
 *  reasons and the ranked alternatives are what a supervisor overriding the
 *  decision needs, and they are already computed server-side.
 *  Mirrors agent_core/treatment/engine.py :: TreatmentResult.to_payload(). */
export type TreatmentSnapshot = {
  action: string;
  actionLabel?: string | null;
  channel?: string | null;
  at?: string | null;
  expectedValueInr?: number | null;
  suppressed?: boolean;
  reason?: string | null;
  reasonText?: string | null;
  rationale?: string;
  decisionId?: string | null;
  propensity?: number | null;
  policyVersion?: number | null;
  mode?: string | null;
  variant?: string | null;
  latencyMs?: number | null;
  alternatives?: TreatmentAlternative[];
  /** action -> veto reason, for the actions arbitration ruled out. */
  excluded?: Record<string, string>;
};

export type CustomerInsights = {
  customerId: string;
  summary: InsightBullet[];
  nba: NbaItem[];
  metrics: BehaviorMetrics;
  activity: ActivityPreviewItem[];
  generatedAt: string;
  offerPolicy?: OfferPolicy | null;
  // No authorityPolicy. The goodwill matrix is env-tunable policy-as-code the
  // server owns (agent_core/authority); this module used to carry a frozen copy
  // of it — dpd >= 61 escalates, ₹500/₹250 caps, two of its eleven escalate
  // reasons — which quietly diverged from the running thresholds. The panel
  // asks GET /authority/next instead: api/authority.ts :: useAuthorityNext.
  //
  // The offline derivation below never produces this — only the server does.
  treatment?: TreatmentSnapshot | null;
};

function daysBetween(iso: string, now = Date.now()): number {
  return Math.round((now - new Date(iso).getTime()) / 86_400_000);
}

/** Safe INR numeral — API fields may be null. */
function inr(n: number | null | undefined): string {
  const value = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return value.toLocaleString("en-IN");
}

function str(value: string | null | undefined, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function sortByIsoDesc<T>(items: T[], iso: (item: T) => string | null | undefined): T[] {
  return [...items].sort((a, b) => str(iso(b)).localeCompare(str(iso(a))));
}

// withinWindow lived here and is gone with the ladder that used it. It parsed
// a display string like "10:00–18:00" out of the customer record and compared
// it to the browser clock — so a rep in a different timezone from the borrower
// got a different answer about whether it was safe to dial, and neither answer
// consulted the statutory calling window. contact_policy owns that question.

function computeMetrics(customer: Customer): BehaviorMetrics {
  const settled = customer.promises.filter((p) => p.status === "kept" || p.status === "broken");
  const kept = customer.promises.filter((p) => p.status === "kept").length;
  const ptpKeepRate = settled.length ? Math.round((kept / settled.length) * 100) : null;

  const lastIx = sortByIsoDesc(customer.interactions, (i) => i.startedAt)[0];
  const contactIso = lastIx?.startedAt ?? customer.lastContact;
  const daysSinceContact = contactIso ? daysBetween(contactIso) : null;

  const openDisputeAmount = customer.disputes
    .filter((d) => d.status !== "resolved" && d.status !== "rejected")
    .reduce((s, d) => s + (d.amount ?? 0), 0);

  const nextEmi =
    customer.emi.find((e) => e.status === "overdue") ??
    customer.emi.find((e) => e.status === "upcoming");
  const brokenPromiseCount = customer.promises.filter((p) => p.status === "broken").length;
  const activePromiseAmount = customer.promises
    .filter((p) => p.status === "upcoming")
    .reduce((s, p) => s + (p.amount ?? 0), 0);

  let paymentStreak = 0;
  for (const e of [...customer.emi].sort((a, b) => a.index - b.index)) {
    if (e.status === "paid") paymentStreak += 1;
    else if (e.status === "partial") break;
    else if (e.status === "overdue" || e.status === "upcoming") break;
  }

  return {
    ptpKeepRate,
    daysSinceContact,
    openDisputeAmount,
    nextEmiAmount: nextEmi?.amount ?? null,
    nextEmiDate: nextEmi?.dueDate ?? null,
    paymentStreak,
    brokenPromiseCount,
    activePromiseAmount,
  };
}

function mockOfferPolicy(customer: Customer): OfferPolicy {
  if (customer.contact.dnd) {
    return {
      ...emptyOfferPolicy(),
      status: "suppressed",
      customerId: customer.id,
      suppressionReason: "dnd",
      suppressionLabel: "DND is on — do not pitch",
    };
  }
  const presented = customer.interactions.some((i) => i.intents?.upsellPresented);
  if (presented) {
    return {
      ...emptyOfferPolicy(),
      status: "presented",
      customerId: customer.id,
      productId: "topup-loan",
      productName: "Top-up Loan",
      suggestedAmount: 150000,
      talkTrack: "You may be eligible for a Top-up Loan of about one point five lakh rupees.",
      preferredWindow: customer.contact.preferredWindow,
      presented: true,
    };
  }
  return { ...emptyOfferPolicy(), customerId: customer.id };
}

function offerNba(policy: OfferPolicy | null | undefined): NbaItem | null {
  if (!policy) return null;
  if (!["ready", "presented", "interested", "open_lead"].includes(policy.status)) return null;
  const product = policy.productName || "an eligible product";
  const amt = fmtOfferAmount(policy.suggestedAmount);
  const follow = policy.status === "open_lead" || policy.status === "interested";
  const window = policy.preferredWindow;
  let reason = policy.talkTrack || "Engine-approved offer for this account.";
  if (window) reason = `${reason} Preferred window: ${window}.`;
  return {
    id: "nba-offer",
    rank: 99,
    title: `${follow ? "Follow up" : "Pitch"} ${product}${amt ? ` · ${amt}` : ""}`,
    reason,
    action: "offer",
    priority: "medium",
    leadId: policy.leadId,
  };
}

// mockAuthorityPolicy lived here and is gone with the matrix it re-implemented.
// It decided goodwill in the browser — dpd >= 61 escalates, ceiling ₹500 under
// 30 DPD and ₹250 above, two escalate reasons — against thresholds the backend
// reads from the environment at call time and an escalate set five times the
// size. api/authority.ts asks the engine, and emulates the *backend's* ladder
// (all of it, env overrides included) when there is no backend to ask.

function buildNba(
  customer: Customer,
  metrics: BehaviorMetrics,
  offerPolicy?: OfferPolicy | null,
): NbaItem[] {
  const items: NbaItem[] = [];
  const openDispute = customer.disputes.find(
    (d) => d.status === "under_review" || d.status === "new",
  );
  const upcomingPtp = customer.promises
    .filter((p) => p.status === "upcoming")
    .sort((a, b) => str(a.promisedDate).localeCompare(str(b.promisedDate)))[0];
  const daysToPtp = upcomingPtp?.promisedDate ? -daysBetween(upcomingPtp.promisedDate) : null;

  // No contact ladder here any more. This function is the *offline* copy —
  // mock mode, and the catch-fallback when the insights API is unreachable —
  // and a second implementation of a decision the engine owns is exactly the
  // drift the backend copy was deleted to stop. What survives is case
  // handling, which the engine does not model.
  items.push({
    id: "nba-engine-unavailable",
    rank: 1,
    title: "Recommendation unavailable",
    reason:
      "The decision engine could not be reached, so this list is case handling only — " +
      "no contact recommendation has been made for this account.",
    action: "wait",
    priority: "low",
  });

  if (openDispute) {
    items.push({
      id: "nba-review-dispute",
      rank: items.length + 1,
      title: "Review open dispute before hard collect",
      reason: `${openDispute.id} is ${str(openDispute.status).replace("_", " ")} (₹${inr(openDispute.amount)}).`,
      action: "review",
      priority: "high",
    });
  }

  if (upcomingPtp && daysToPtp !== null && daysToPtp <= 3) {
    items.push({
      id: "nba-confirm-ptp",
      rank: items.length + 1,
      title: "Confirm upcoming PTP channel",
      reason: `₹${inr(upcomingPtp.amount)} promised ${daysToPtp <= 0 ? "today/overdue" : `in ${daysToPtp}d`} via ${upcomingPtp.channel}.`,
      action: "ptp",
      priority: daysToPtp <= 1 ? "high" : "medium",
    });
  }

  if (metrics.brokenPromiseCount > 0) {
    items.push({
      id: "nba-smaller-ptp",
      rank: items.length + 1,
      title: "Offer smaller PTP or payment plan",
      reason: `${metrics.brokenPromiseCount} broken promise(s) on file — avoid repeating full-balance asks.`,
      action: "ptp",
      priority: "medium",
    });
  }

  if (!customer.documents.some((d) => d.status === "sent" || d.status === "generating")) {
    items.push({
      id: "nba-send-statement",
      rank: items.length + 1,
      title: "Send account statement",
      reason: "No recent statement delivery on file — useful before negotiation.",
      action: "statement",
      priority: "low",
    });
  }

  const offerItem = offerNba(offerPolicy);
  if (offerItem) items.push(offerItem);

  if (items.length === 0) {
    items.push({
      id: "nba-log-touch",
      rank: 1,
      title: "Log a soft touchpoint",
      reason: "Account is stable — capture a note or confirm next EMI.",
      action: "call",
      priority: "low",
    });
  }

  return items
    .sort((a, b) => {
      const p = { high: 0, medium: 1, low: 2 };
      return p[a.priority] - p[b.priority] || a.rank - b.rank;
    })
    .map((item, i) => ({ ...item, rank: i + 1 }))
    .slice(0, 5);
}

function buildSummary(
  customer: Customer,
  metrics: BehaviorMetrics,
  nba: NbaItem[],
  offerPolicy?: OfferPolicy | null,
): InsightBullet[] {
  const bullets: InsightBullet[] = [];

  bullets.push({
    id: "ins-position",
    text: `${customer.name} is in bucket ${customer.account.bucket} at ${customer.account.dpd} DPD with ₹${inr(customer.outstanding)} outstanding (min due ₹${inr(customer.minimumDue)}).`,
    source: "from account position",
    confidence: "high",
  });

  if (metrics.ptpKeepRate !== null) {
    bullets.push({
      id: "ins-ptp",
      text:
        metrics.ptpKeepRate >= 50
          ? `PTP keep-rate is ${metrics.ptpKeepRate}% — customer has some follow-through; prefer confirmed smaller commitments.`
          : `PTP keep-rate is only ${metrics.ptpKeepRate}% with ${metrics.brokenPromiseCount} broken — treat new promises cautiously.`,
      source: "from PTP history",
      confidence: "high",
    });
  } else if (metrics.activePromiseAmount > 0) {
    bullets.push({
      id: "ins-ptp-active",
      text: `₹${inr(metrics.activePromiseAmount)} in active promises with no settled history yet — confirm channel and ability to pay.`,
      source: "from PTP history",
      confidence: "medium",
    });
  }

  const lastIx = sortByIsoDesc(customer.interactions, (i) => i.startedAt)[0];
  if (lastIx) {
    const summary = str(lastIx.summary);
    const clipped = summary.slice(0, 120);
    const handlerName = str(lastIx.handler?.name, "Unknown");
    bullets.push({
      id: "ins-last-ix",
      text: `Last ${str(lastIx.channel, "channel")} touch (${handlerName}): “${clipped}${summary.length > 120 ? "…" : ""}” — sentiment ${str(lastIx.sentiment, "neutral")}.`,
      source: "from last interaction",
      confidence: "high",
    });
  }

  const openDispute = customer.disputes.find(
    (d) => d.status !== "resolved" && d.status !== "rejected",
  );
  if (openDispute) {
    bullets.push({
      id: "ins-dispute",
      text: `Open dispute ${openDispute.id} (₹${inr(openDispute.amount)}) is ${str(openDispute.status).replace(/_/g, " ")} — avoid aggressive collection until resolved.`,
      source: "from disputes",
      confidence: "high",
    });
  }

  // No "from authority matrix" bullet. It restated a verdict this file was
  // inventing; the Authority panel now renders the server's, and a summary line
  // paraphrasing a ceiling from a second source is how the two drift apart.

  if (offerPolicy?.status === "suppressed") {
    bullets.push({
      id: "ins-offer-quiet",
      text: `Offer engine quiet: ${offerPolicy.suppressionLabel ?? offerPolicy.suppressionReason ?? "stayed quiet"}. Do not freelance a product.`,
      source: "from offer policy",
      confidence: "high",
    });
  }

  if (nba[0]) {
    bullets.push({
      id: "ins-nba",
      text: `Recommended next step: ${nba[0].title}. ${nba[0].reason}`,
      source: "from next-best-action rules",
      confidence: "medium",
    });
  }

  return bullets.slice(0, 5);
}

function synthesizeActivity(customer: Customer): ActivityPreviewItem[] {
  const items: ActivityPreviewItem[] = [];

  for (const ix of customer.interactions) {
    items.push({
      id: `act-ix-${ix.id}`,
      kind: "interaction",
      label: `${str(ix.channel, "channel")} · ${str(ix.disposition, "unknown")}`,
      note: str(ix.summary) || null,
      at: str(ix.startedAt),
      tone: ix.sentiment,
    });
  }
  for (const p of customer.promises) {
    items.push({
      id: `act-ptp-${p.id}`,
      kind: "promise",
      label: `PTP ${str(p.status, "unknown")} · ₹${inr(p.amount)}`,
      note: `via ${str(p.channel, "—")} · ${str(p.handler, "—")}`,
      at: str(p.createdAt),
      tone: p.status === "broken" ? "negative" : p.status === "kept" ? "positive" : null,
    });
  }
  for (const d of customer.disputes) {
    items.push({
      id: `act-d-${d.id}`,
      kind: "dispute",
      label: `Dispute ${str(d.status).replace(/_/g, " ") || "open"}`,
      note: d.transcriptSnippet,
      at: str(d.filedAt),
      tone: "warning",
    });
  }
  for (const n of customer.notes) {
    items.push({
      id: `act-n-${n.id}`,
      kind: "note",
      label: n.pinned ? "Pinned note" : "Note added",
      note: n.text,
      at: str(n.at),
      tone: null,
    });
  }
  for (const doc of customer.documents) {
    items.push({
      id: `act-doc-${doc.id}`,
      kind: "document",
      label: `${str(doc.type, "document")} · ${str(doc.status, "unknown")}`,
      note: `via ${str(doc.deliveryChannel, "—")}`,
      at: str(doc.requestedAt),
      tone: null,
    });
  }

  return items
    .filter((item) => item.at)
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, 8);
}

/** Deterministic Customer 360 insights — works offline / mock without LLM. */
export function deriveCustomerInsights(customer: Customer): CustomerInsights {
  const metrics = computeMetrics(customer);
  const offerPolicy = mockOfferPolicy(customer);
  const nba = buildNba(customer, metrics, offerPolicy);
  const summary = buildSummary(customer, metrics, nba, offerPolicy);
  const activity = synthesizeActivity(customer);
  return {
    customerId: customer.id,
    summary,
    nba,
    metrics,
    activity,
    generatedAt: new Date().toISOString(),
    offerPolicy,
  };
}
