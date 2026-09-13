import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { InsightsPanel } from "./InsightsPanel";
import { NextBestActionCard } from "./NextBestActionCard";
import { BehaviorMetricsStrip } from "./BehaviorMetricsStrip";
import { ActivityTimeline } from "./ActivityTimeline";
import { authorityPolicyFromNext, useApplyAuthority, useAuthorityNext } from "@/api/authority";
import { useCaptureLeadFromPolicy } from "@/api/upsell";
import { AuthorityPolicyBlock } from "@/components/offers/AuthorityPolicyBlock";
import { OfferPolicyBlock } from "@/components/offers/OfferPolicyBlock";
import type { CustomerInsights, NbaActionKind } from "@/api/types/customer-insights";

export function OverviewTab({
  insights,
  onNbaAction,
}: {
  insights: CustomerInsights;
  onNbaAction: (action: NbaActionKind) => void;
}) {
  const navigate = useNavigate();
  // The allowed move comes from the engine that owns it (GET /authority/next).
  // This panel used to render a client-side re-implementation of the matrix,
  // frozen at ₹500/₹250 and two escalate reasons while the real one stayed
  // env-tunable and grew to eleven.
  const authorityQuery = useAuthorityNext(insights.customerId);
  const authorityPolicy = authorityQuery.data
    ? authorityPolicyFromNext(authorityQuery.data, insights.customerId)
    : null;
  const authorityState = authorityQuery.isError
    ? "unavailable"
    : authorityQuery.isPending || !authorityPolicy
      ? "pending"
      : "ready";
  const captureMut = useCaptureLeadFromPolicy();
  const applyMut = useApplyAuthority(insights.customerId);
  const capture = () => {
    const policy = insights.offerPolicy;
    if (!policy?.productId) {
      toast.error("No approved product to capture");
      return;
    }
    captureMut.mutate(
      {
        customerId: insights.customerId,
        productId: policy.productId,
        indicativeAmount: policy.suggestedAmount,
        decisionId: policy.decisionId,
        interactionId: policy.interactionId,
        channel: policy.channel,
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
    if (!authorityPolicy?.decisionId) return;
    applyMut.mutate({
      decisionId: authorityPolicy.decisionId,
      amount: authorityPolicy.approvedAmount,
      disputeId: authorityPolicy.disputeId,
    });
  };

  return (
    <div className="space-y-200">
      <BehaviorMetricsStrip metrics={insights.metrics} />
      <AuthorityPolicyBlock
        policy={authorityPolicy}
        state={authorityState}
        className="rounded-large border border-border bg-surface !border-t"
        // Only offered when there is a recorded decision to post against. The
        // mock emulates the verdict but records nothing, so it has no id.
        onApply={authorityPolicy?.decisionId ? apply : undefined}
        applying={applyMut.isPending}
      />
      {insights.offerPolicy && insights.offerPolicy.status !== "none" ? (
        <OfferPolicyBlock
          policy={insights.offerPolicy}
          className="rounded-large border border-border bg-surface !border-t"
          onCapture={capture}
          capturing={captureMut.isPending}
        />
      ) : null}
      <div className="grid gap-200 lg:grid-cols-2">
        <InsightsPanel bullets={insights.summary} />
        <NextBestActionCard items={insights.nba} onAction={onNbaAction} />
      </div>
      <ActivityTimeline items={insights.activity} />
    </div>
  );
}
