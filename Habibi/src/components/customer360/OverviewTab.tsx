import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { InsightsPanel } from "./InsightsPanel";
import { NextBestActionCard } from "./NextBestActionCard";
import { BehaviorMetricsStrip } from "./BehaviorMetricsStrip";
import { ActivityTimeline } from "./ActivityTimeline";
import { applyAuthority, authorityPolicyFromNext, useAuthorityNext } from "@/api/authority";
import { captureLeadFromPolicy } from "@/api/upsell";
import { AuthorityPolicyBlock } from "@/components/offers/AuthorityPolicyBlock";
import { OfferPolicyBlock } from "@/components/offers/OfferPolicyBlock";
import type { CustomerInsights, NbaActionKind } from "@/lib/customerInsights";

export function OverviewTab({
  insights,
  onNbaAction,
}: {
  insights: CustomerInsights;
  onNbaAction: (action: NbaActionKind) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
  const captureMut = useMutation({
    mutationFn: () => {
      const policy = insights.offerPolicy;
      if (!policy?.productId) throw new Error("No approved product to capture");
      return captureLeadFromPolicy({
        customerId: insights.customerId,
        productId: policy.productId,
        indicativeAmount: policy.suggestedAmount,
        decisionId: policy.decisionId,
        interactionId: policy.interactionId,
        channel: policy.channel,
        note: policy.talkTrack,
      });
    },
    onSuccess: (lead) => {
      toast.success("Lead captured");
      void queryClient.invalidateQueries({ queryKey: ["customer-insights", insights.customerId] });
      void queryClient.invalidateQueries({ queryKey: ["leads"] });
      void navigate({ to: "/upsell", search: { id: lead.id } });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Lead capture failed"),
  });
  const applyMut = useMutation({
    mutationFn: () => {
      if (!authorityPolicy?.decisionId) throw new Error("No authority decision to apply");
      return applyAuthority({
        decisionId: authorityPolicy.decisionId,
        amount: authorityPolicy.approvedAmount,
        disputeId: authorityPolicy.disputeId,
      });
    },
    onSuccess: () => {
      toast.success("Goodwill posted");
      // The verdict changes the moment goodwill posts — a second waiver in the
      // same 12 months is an escalate — so re-ask rather than keep this one.
      void queryClient.invalidateQueries({ queryKey: ["authority-next", insights.customerId] });
      void queryClient.invalidateQueries({ queryKey: ["customer-insights", insights.customerId] });
      void queryClient.invalidateQueries({ queryKey: ["customer", insights.customerId] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Goodwill apply failed"),
  });

  return (
    <div className="space-y-200">
      <BehaviorMetricsStrip metrics={insights.metrics} />
      <AuthorityPolicyBlock
        policy={authorityPolicy}
        state={authorityState}
        className="rounded-large border border-border bg-surface !border-t"
        // Only offered when there is a recorded decision to post against. The
        // mock emulates the verdict but records nothing, so it has no id.
        onApply={authorityPolicy?.decisionId ? () => applyMut.mutate() : undefined}
        applying={applyMut.isPending}
      />
      {insights.offerPolicy && insights.offerPolicy.status !== "none" ? (
        <OfferPolicyBlock
          policy={insights.offerPolicy}
          className="rounded-large border border-border bg-surface !border-t"
          onCapture={() => captureMut.mutate()}
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
