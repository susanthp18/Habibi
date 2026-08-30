import { AlertTriangle, Ban, CheckCircle2, Clock, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Contact } from "@/data/customer360-seed";
import { useContactPolicy, type ContactPolicy } from "@/api/contact-policy";
import { StatusChip, type ChipTone } from "./StatusChip";

type Props = { customerId: string; contact: Contact; className?: string; compact?: boolean };

/**
 * The pill answers a compliance question, so it renders the backend's verdict
 * and nothing else.
 *
 * It used to recompute the calling window in the browser: it parsed the
 * borrower's display window out of the customer record and compared it to
 * `new Date()` in the AGENT's timezone. That got four things wrong at once — an
 * agent in another zone saw a different answer than the borrower's quiet hours
 * warranted, a borrower with no stated window was always "OK to contact"
 * (the statutory RBI 08:00–19:00 bound was never applied), consented days were
 * ignored entirely, and the end of the window was inclusive where the veto
 * treats it as exclusive, so 19:00 sharp showed green against a blocking
 * dialler. contact_policy.py owns this question; we ask it.
 */

/** Verdict states the chip can be in. Only "ok" is green. */
type ContactabilityStatus = "pending" | "ok" | "blocked" | "unknown";

export interface ContactabilityView {
  status: ContactabilityStatus;
  tone: ChipTone;
  label: string;
  sub: string;
  ok: boolean;
}

/**
 * Formatter over contact_policy.py's reason codes. Every branch that is not an
 * explicit `allowed: true` is non-green, including unrecognised codes — a
 * reason this build has never heard of is still a refusal, and must not fall
 * through to "OK to contact".
 */
function describeReason(
  reason: string | null,
  contact: Contact,
  policy: ContactPolicy,
): { tone: ChipTone; label: string; sub: string } {
  switch (reason) {
    case "channel_opted_out":
      return { tone: "danger", label: "Voice opt-out", sub: "Use WhatsApp / Email only" };
    case "channel_dnd":
      return { tone: "danger", label: "DND active", sub: "Voice channel marked DND" };
    case "channel_expired":
      return { tone: "danger", label: "Consent expired", sub: "Re-capture consent before calling" };
    case "customer_dnd":
      return { tone: "danger", label: "DND active", sub: "Use WhatsApp / Email only" };
    case "no_promotional_consent":
      return { tone: "danger", label: "No promotional consent", sub: "Servicing contact only" };
    case "outside_calling_hours":
      return {
        tone: "warning",
        label: "Outside calling hours",
        sub: `Statutory 08:00–19:00 · ${contact.timezone}`,
      };
    case "outside_allowed_window":
      return {
        tone: "warning",
        label: "Outside contact window",
        sub: `Next allowed · ${contact.preferredWindow}`,
      };
    case "cooling_off":
      return { tone: "warning", label: "Cooling-off period", sub: "Too soon since last contact" };
    case "daily_cap":
      return {
        tone: "warning",
        label: "Daily cap reached",
        sub: `${policy.outreachToday} of ${policy.dailyCap} touches used today`,
      };
    case "weekly_cap":
      return { tone: "warning", label: "Weekly cap reached", sub: "Weekly contact limit hit" };
    case "no_customer":
      return { tone: "warning", label: "Customer not found", sub: "Policy could not be resolved" };
    case "consent_unreadable":
      return {
        tone: "warning",
        label: "Consent unreadable",
        sub: "Blocked until consent resolves",
      };
    default:
      return {
        tone: "warning",
        label: "Contact blocked",
        sub: reason ? `Policy reason · ${reason}` : "Blocked by contact policy",
      };
  }
}

/**
 * Turns a query result into the chip's state. Kept exported and pure so the
 * loading and failure branches are inspectable without a live backend.
 *
 * Fail-closed, exactly as contact_policy.evaluate() does: while the verdict is
 * in flight the chip is neutral and never claims contactability, and if the
 * call fails it says so rather than defaulting to green.
 */
export function contactabilityState(
  contact: Contact,
  query: { data?: ContactPolicy; isPending: boolean; isError: boolean },
): ContactabilityView {
  if (query.isError || (!query.isPending && !query.data)) {
    return {
      status: "unknown",
      tone: "warning",
      label: "Contact policy unavailable",
      sub: "Cannot confirm — treat as do-not-contact",
      ok: false,
    };
  }
  if (query.isPending || !query.data) {
    return {
      status: "pending",
      tone: "neutral",
      label: "Checking contact policy",
      sub: "Awaiting policy verdict",
      ok: false,
    };
  }

  const policy = query.data;
  if (policy.allowed) {
    return {
      status: "ok",
      tone: "success",
      label: "OK to contact",
      sub: `Voice window · ${contact.preferredWindow}`,
      ok: true,
    };
  }
  const { tone, label, sub } = describeReason(policy.reason, contact, policy);
  return { status: "blocked", tone, label, sub, ok: false };
}

function iconFor(status: ContactabilityStatus, tone: ChipTone) {
  if (status === "pending") return <Loader2 className="h-3 w-3 shrink-0 animate-spin" />;
  if (status === "unknown") return <AlertTriangle className="h-3 w-3 shrink-0" />;
  if (tone === "danger") return <Ban className="h-3 w-3 shrink-0" />;
  if (tone === "warning") return <Clock className="h-3 w-3 shrink-0" />;
  return <CheckCircle2 className="h-3 w-3 shrink-0" />;
}

export function ContactabilityPill({ customerId, contact, className, compact }: Props) {
  const query = useContactPolicy(customerId, { channel: "voice", purpose: "outreach" });
  const { status, tone, label, sub } = contactabilityState(contact, query);

  return (
    <StatusChip
      label={compact ? label : `${label} · ${sub}`}
      tone={tone}
      shape="pill"
      size="sm"
      title={sub}
      className={cn("normal-case tracking-normal", className)}
    >
      {iconFor(status, tone)}
    </StatusChip>
  );
}
