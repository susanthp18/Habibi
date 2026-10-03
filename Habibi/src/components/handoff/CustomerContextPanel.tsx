import type { ReactNode } from "react";
import { AlertOctagon, CalendarClock, ExternalLink, HandCoins, User2 } from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import type { ActiveCall, CustomerContext } from "@/api/handoff";
import { useCaptureLeadFromPolicy } from "@/api/upsell";
import { useApplyAuthority } from "@/api/authority";
import { OfferPolicyBlock } from "@/components/offers/OfferPolicyBlock";
import { AuthorityPolicyBlock } from "@/components/offers/AuthorityPolicyBlock";
import { Lozenge } from "@/components/ui/lozenge";
import { ContactabilityPill } from "@/components/customer360/ContactabilityPill";
import { RiskLozenge } from "./HandoffQueue";
import { fmtShortDate } from "@/lib/format";

export function CustomerContextPanel({
  call: activeCall,
  context: c,
  readOnly = false,
}: {
  call: ActiveCall;
  context: CustomerContext;
  /** Watching someone else's case: nothing here may be applied or captured. */
  readOnly?: boolean;
}) {
  const money = (n: number) => `${c.currency}${n.toLocaleString("en-IN")}`;
  const ptpStatus = (c.lastPromise?.status || "").toLowerCase();
  const navigate = useNavigate();
  const captureMut = useCaptureLeadFromPolicy();
  const applyMut = useApplyAuthority(activeCall.customerId);
  const capture = () => {
    const policy = c.offerPolicy;
    if (!policy?.productId) {
      toast.error("No approved product to capture");
      return;
    }
    captureMut.mutate(
      {
        customerId: activeCall.customerId,
        productId: policy.productId,
        indicativeAmount: policy.suggestedAmount,
        decisionId: policy.decisionId,
        interactionId: activeCall.interactionId,
        channel: policy.channel ?? activeCall.channel,
        note: policy.talkTrack,
      },
      {
        onSuccess: (lead) => {
          toast.success("Lead captured");
          void navigate({ to: "/upsell", search: { id: lead.id } });
        },
      },
    );
  };
  const apply = () => {
    const policy = c.authorityPolicy;
    if (!policy?.decisionId) {
      toast.error("No authority decision to apply");
      return;
    }
    applyMut.mutate({
      decisionId: policy.decisionId,
      amount: policy.approvedAmount,
      disputeId: policy.disputeId,
    });
  };

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <User2 className="h-3.5 w-3.5 text-text-brand" />
          Customer context
        </div>
        <RiskLozenge risk={c.risk} />
      </div>

      <div className="px-150 py-150">
        {/* A new tab: the case stays open where the agent left it. */}
        <Link
          to="/customers/$customerId"
          params={{ customerId: activeCall.customerId }}
          target="_blank"
          rel="noopener"
          className="inline-flex items-center gap-050 text-body-small font-semibold text-text-brand hover:underline"
        >
          Open Customer 360
          <ExternalLink className="h-3 w-3" />
        </Link>
        <div className="mt-050 text-body-small text-text-subtlest">Outstanding · this loan</div>
        <div className="tabular heading-large font-semibold text-text">
          {c.outstanding == null ? "—" : money(c.outstanding)}
        </div>
        <div className="text-body-small text-text-subtle">
          {c.product}
          {c.tenureMonths ? ` · tenure ${c.tenureMonths}m` : ""}
        </div>
      </div>

      <ul className="divide-y divide-border border-t border-border">
        <Row
          icon={<HandCoins className="h-3.5 w-3.5 text-text-warning" />}
          label="Last promise · any loan"
          value={
            c.lastPromise
              ? `${money(c.lastPromise.amount)} · ${fmtShortDate(c.lastPromise.date)}`
              : "None on file"
          }
          badge={
            c.lastPromise
              ? {
                  text: ptpStatus || "open",
                  tone:
                    ptpStatus === "broken"
                      ? "danger"
                      : ptpStatus === "kept"
                        ? "success"
                        : "warning",
                }
              : { text: "—", tone: "info" }
          }
        />
        <Row
          icon={<CalendarClock className="h-3.5 w-3.5 text-text-brand" />}
          label="Next EMI"
          value={
            c.nextEmi
              ? `${money(c.nextEmi.amount)} · due ${fmtShortDate(c.nextEmi.dueDate)}`
              : "No upcoming EMI"
          }
          badge={
            c.nextEmi && c.nextEmi.daysOverdue > 0
              ? { text: `${c.nextEmi.daysOverdue}d overdue`, tone: "warning" }
              : { text: c.nextEmi ? "On track" : "—", tone: c.nextEmi ? "success" : "info" }
          }
        />
        <Row
          icon={<AlertOctagon className="h-3.5 w-3.5 text-text-danger" />}
          label="Open disputes · any loan"
          value={`${c.openDisputes} active`}
          badge={{
            text: c.openDisputes > 0 ? "Open" : "Clear",
            tone: c.openDisputes > 0 ? "info" : "success",
          }}
        />
      </ul>

      {/* The contact gate's own verdict for a call back now, not a re-derivation. */}
      <div className="flex flex-wrap items-center gap-075 border-t border-border px-150 py-100">
        <span className="text-body-small text-text-subtlest">Calling back now</span>
        <ContactabilityPill customerId={activeCall.customerId} compact />
      </div>

      {c.authorityPolicy ? (
        <AuthorityPolicyBlock
          policy={c.authorityPolicy}
          onApply={readOnly ? undefined : apply}
          applying={applyMut.isPending}
        />
      ) : (
        <Unavailable what="authority decision" />
      )}

      {c.offerPolicy ? (
        <OfferPolicyBlock
          policy={c.offerPolicy}
          onCapture={readOnly ? undefined : capture}
          capturing={captureMut.isPending}
        />
      ) : (
        <Unavailable what="offer decision" />
      )}
    </div>
  );
}

function Unavailable({ what }: { what: string }) {
  return (
    <p
      role="status"
      className="border-t border-border px-150 py-100 text-body-small text-text-warning"
    >
      Couldn't load the {what}. Check it in Customer 360 before offering anything.
    </p>
  );
}

function Row({
  icon,
  label,
  value,
  badge,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  badge: { text: string; tone: "danger" | "warning" | "success" | "info" };
}) {
  const toneMap = {
    danger: "danger",
    warning: "warning",
    success: "success",
    info: "selected",
  } as const;
  return (
    <li className="flex items-start gap-100 px-150 py-100">
      <span className="mt-025">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-body-small text-text-subtlest">{label}</div>
        <div className="truncate text-body-small text-text">{value}</div>
      </div>
      <Lozenge tone={toneMap[badge.tone]} className="shrink-0">
        {badge.text}
      </Lozenge>
    </li>
  );
}
