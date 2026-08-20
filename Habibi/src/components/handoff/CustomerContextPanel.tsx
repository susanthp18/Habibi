import type { ReactNode } from "react";
import { AlertOctagon, CalendarClock, HandCoins, ShieldCheck, User2 } from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ActiveCall, CustomerContext } from "@/api/handoff";
import { captureLeadFromPolicy } from "@/api/upsell";
import { applyAuthority } from "@/api/authority";
import { OfferPolicyBlock } from "@/components/offers/OfferPolicyBlock";
import { AuthorityPolicyBlock } from "@/components/offers/AuthorityPolicyBlock";
import { Lozenge } from "@/components/ui/lozenge";
import { RiskLozenge } from "./HandoffQueue";

function fmtDate(raw: string) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function CustomerContextPanel({
  call: activeCall,
  context: c,
}: {
  call: ActiveCall;
  context: CustomerContext;
}) {
  const money = (n: number) => `${c.currency}${n.toLocaleString("en-IN")}`;
  const ptpStatus = (c.lastPromise?.status || "").toLowerCase();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const captureMut = useMutation({
    mutationFn: () => {
      const policy = c.offerPolicy;
      if (!policy?.productId) throw new Error("No approved product to capture");
      return captureLeadFromPolicy({
        customerId: activeCall.customerId,
        productId: policy.productId,
        indicativeAmount: policy.suggestedAmount,
        decisionId: policy.decisionId,
        interactionId: activeCall.interactionId,
        channel: policy.channel ?? activeCall.channel,
        note: policy.talkTrack,
      });
    },
    onSuccess: (lead) => {
      toast.success("Lead captured");
      void queryClient.invalidateQueries({ queryKey: ["handoff"] });
      void queryClient.invalidateQueries({ queryKey: ["leads"] });
      void navigate({ to: "/upsell", search: { id: lead.id } });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Lead capture failed"),
  });
  const applyMut = useMutation({
    mutationFn: () => {
      const policy = c.authorityPolicy;
      if (!policy?.decisionId) throw new Error("No authority decision to apply");
      return applyAuthority({
        decisionId: policy.decisionId,
        amount: policy.approvedAmount,
        disputeId: policy.disputeId,
      });
    },
    onSuccess: () => {
      toast.success("Goodwill posted");
      void queryClient.invalidateQueries({ queryKey: ["handoff"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Goodwill apply failed"),
  });
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
        <Link
          to="/customers/$customerId"
          params={{ customerId: activeCall.customerId }}
          className="text-body-small font-semibold text-text-brand hover:underline"
        >
          Open Customer 360
        </Link>
        <div className="mt-050 text-body-small text-text-subtlest">Outstanding</div>
        <div className="tabular text-[1.5rem] font-semibold text-text">{money(c.outstanding)}</div>
        <div className="text-body-small text-text-subtle">
          {c.product}
          {c.tenureMonths ? ` · tenure ${c.tenureMonths}m` : ""}
        </div>
      </div>

      <ul className="divide-y divide-border border-t border-border">
        <Row
          icon={<HandCoins className="h-3.5 w-3.5 text-text-warning" />}
          label="Last promise"
          value={
            c.lastPromise
              ? `${money(c.lastPromise.amount)} · ${fmtDate(c.lastPromise.date)}`
              : "None on file"
          }
          badge={
            c.lastPromise
              ? {
                  text: ptpStatus || "open",
                  tone: ptpStatus === "broken" ? "danger" : ptpStatus === "kept" ? "success" : "warning",
                }
              : { text: "—", tone: "info" }
          }
        />
        <Row
          icon={<CalendarClock className="h-3.5 w-3.5 text-text-brand" />}
          label="Next EMI"
          value={
            c.nextEmi ? `${money(c.nextEmi.amount)} · due ${fmtDate(c.nextEmi.dueDate)}` : "No upcoming EMI"
          }
          badge={
            c.nextEmi && c.nextEmi.daysOverdue > 0
              ? { text: `${c.nextEmi.daysOverdue}d overdue`, tone: "warning" }
              : { text: c.nextEmi ? "On track" : "—", tone: c.nextEmi ? "success" : "info" }
          }
        />
        <Row
          icon={<AlertOctagon className="h-3.5 w-3.5 text-text-danger" />}
          label="Open disputes"
          value={`${c.openDisputes} active`}
          badge={{
            text: c.openDisputes > 0 ? "Open" : "Clear",
            tone: c.openDisputes > 0 ? "info" : "success",
          }}
        />
        <Row
          icon={<ShieldCheck className="h-3.5 w-3.5 text-text-success" />}
          label="Consent / DND"
          value={`${c.dnd.window || "No window"} · ${c.dnd.channels.join(", ")}`}
          badge={{
            text: c.dnd.allowed ? "Contactable" : "Blocked",
            tone: c.dnd.allowed ? "success" : "danger",
          }}
        />
      </ul>

      <AuthorityPolicyBlock
        policy={c.authorityPolicy}
        onApply={() => applyMut.mutate()}
        applying={applyMut.isPending}
      />

      <OfferPolicyBlock
        policy={c.offerPolicy}
        onCapture={() => captureMut.mutate()}
        capturing={captureMut.isPending}
      />

      <div className="border-t border-border px-150 py-100 text-body-small text-text-subtlest">
        Escalation: <span className="text-text-subtle">{activeCall.escalationReason}</span>
        {c.liveQa?.reason ? (
          <span className="mt-025 block text-text-subtle">
            Floor: {c.liveQa.reason.replace(/-/g, " ")}
            {c.liveQa.status === "would_barge" ? " (shadow — would barge)" : ""}
          </span>
        ) : null}
      </div>
    </div>
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
