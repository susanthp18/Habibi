import type { Customer } from "@/data/customer360-seed";
import { emptyOfferPolicy, fmtOfferAmount, type OfferPolicy } from "@/lib/offer-policy";
import { emptyAuthorityPolicy, fmtAuthorityAmount, type AuthorityPolicy } from "@/lib/authority-policy";

export type NbaActionKind = "ptp" | "dispute" | "statement" | "call" | "callback" | "review" | "offer";

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

export type CustomerInsights = {
  customerId: string;
  summary: InsightBullet[];
  nba: NbaItem[];
  metrics: BehaviorMetrics;
  activity: ActivityPreviewItem[];
  generatedAt: string;
  offerPolicy?: OfferPolicy | null;
  authorityPolicy?: AuthorityPolicy | null;
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

function withinWindow(pref: string | null | undefined): boolean {
  const m = str(pref).match(/(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})/);
  if (!m) return true;
  const start = Number(m[1]) * 60 + Number(m[2]);
  const end = Number(m[3]) * 60 + Number(m[4]);
  const now = new Date();
  const cur = now.getHours() * 60 + now.getMinutes();
  return cur >= start && cur <= end;
}

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

  const nextEmi = customer.emi.find((e) => e.status === "overdue") ?? customer.emi.find((e) => e.status === "upcoming");
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

function mockAuthorityPolicy(customer: Customer): AuthorityPolicy {
  const priorWaiver = customer.ledger.some((e) => e.type === "waiver");
  const feeWaiver = customer.disputes.find(
    (d) => d.type === "fee_waiver" && d.status !== "resolved" && d.status !== "rejected",
  );
  if (!feeWaiver && !priorWaiver) {
    return { ...emptyAuthorityPolicy(), customerId: customer.id };
  }
  if (priorWaiver || customer.account.dpd >= 61) {
    const reason = priorWaiver ? "prior_goodwill_12m" : "dpd_too_high";
    const reasonLabel = priorWaiver
      ? "Goodwill already used in the last 12 months"
      : "DPD too high for live goodwill";
    return {
      ...emptyAuthorityPolicy(),
      status: "escalate",
      customerId: customer.id,
      feeType: "late_fee",
      verdict: "escalate",
      reason,
      reasonLabel,
      talkTrack: priorWaiver
        ? "A goodwill waiver already posted in the last 12 months. Escalate — do not offer another reversal on this call."
        : "Out of policy for live goodwill — DPD is too high. Transfer; do not quote a waiver amount.",
    };
  }
  const cap = customer.account.dpd <= 30 ? 500 : 250;
  return {
    ...emptyAuthorityPolicy(),
    status: "shadow",
    customerId: customer.id,
    mode: "shadow",
    feeType: "late_fee",
    verdict: "cap_inr",
    approvedAmount: cap,
    capAmount: cap,
    reason: "cap_available",
    reasonLabel: "In-policy goodwill ceiling",
    talkTrack: `Goodwill ceiling is ${fmtAuthorityAmount(cap)}. You may reverse up to that. If they insist on more, escalate without quoting a larger number.`,
  };
}

function buildNba(customer: Customer, metrics: BehaviorMetrics, offerPolicy?: OfferPolicy | null): NbaItem[] {
  const items: NbaItem[] = [];
  const callOptedIn = customer.consent.find((c) => c.channel === "call")?.optedIn ?? false;
  const inWindow = withinWindow(customer.contact.preferredWindow);
  const openDispute = customer.disputes.find((d) => d.status === "under_review" || d.status === "new");
  const upcomingPtp = customer.promises
    .filter((p) => p.status === "upcoming")
    .sort((a, b) => str(a.promisedDate).localeCompare(str(b.promisedDate)))[0];
  const daysToPtp = upcomingPtp?.promisedDate ? -daysBetween(upcomingPtp.promisedDate) : null;

  if (customer.contact.dnd || !callOptedIn) {
    items.push({
      id: "nba-callback-channel",
      rank: 1,
      title: "Use WhatsApp / email — voice blocked",
      reason: customer.contact.dnd ? "DND is active on this account." : "Customer opted out of voice.",
      action: "callback",
      priority: "high",
    });
  } else if (!inWindow) {
    items.push({
      id: "nba-schedule-callback",
      rank: 1,
      title: "Schedule callback in contact window",
      reason: `Outside preferred window (${customer.contact.preferredWindow}). Do not dial now.`,
      action: "callback",
      priority: "high",
    });
  }

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

  if (
    customer.account.dpd > 30 &&
    (metrics.daysSinceContact === null || metrics.daysSinceContact >= 7) &&
    callOptedIn &&
    !customer.contact.dnd
  ) {
    items.push({
      id: "nba-outbound-call",
      rank: items.length + 1,
      title: "Log outbound collections call",
      reason: `DPD ${customer.account.dpd} with ${metrics.daysSinceContact ?? "no"} day(s) since last contact.`,
      action: "call",
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
  authorityPolicy?: AuthorityPolicy | null,
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

  const openDispute = customer.disputes.find((d) => d.status !== "resolved" && d.status !== "rejected");
  if (openDispute) {
    bullets.push({
      id: "ins-dispute",
      text: `Open dispute ${openDispute.id} (₹${inr(openDispute.amount)}) is ${str(openDispute.status).replace(/_/g, " ")} — avoid aggressive collection until resolved.`,
      source: "from disputes",
      confidence: "high",
    });
  }

  if (authorityPolicy && authorityPolicy.status !== "none") {
    let text: string;
    if (authorityPolicy.status === "escalate") {
      text = `Live goodwill is out of policy: ${authorityPolicy.reasonLabel ?? authorityPolicy.reason ?? "escalate"}. Do not quote a waiver or settlement figure.`;
    } else if (authorityPolicy.status === "applied") {
      const amt = fmtAuthorityAmount(authorityPolicy.approvedAmount);
      text = `Goodwill already posted${amt ? ` (${amt})` : ""}.`;
    } else {
      const amt = fmtAuthorityAmount(authorityPolicy.approvedAmount);
      text = amt
        ? `In-policy late-fee goodwill up to ${amt}.`
        : "Authority matrix has an allowed move — do not invent a larger figure.";
    }
    bullets.push({
      id: "ins-authority",
      text,
      source: "from authority matrix",
      confidence: "high",
    });
  }

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
  const authorityPolicy = mockAuthorityPolicy(customer);
  const nba = buildNba(customer, metrics, offerPolicy);
  const summary = buildSummary(customer, metrics, nba, offerPolicy, authorityPolicy);
  const activity = synthesizeActivity(customer);
  return {
    customerId: customer.id,
    summary,
    nba,
    metrics,
    activity,
    generatedAt: new Date().toISOString(),
    offerPolicy,
    authorityPolicy,
  };
}
