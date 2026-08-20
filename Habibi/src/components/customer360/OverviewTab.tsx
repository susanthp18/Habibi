import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { InsightsPanel } from "./InsightsPanel";
import { NextBestActionCard } from "./NextBestActionCard";
import { BehaviorMetricsStrip } from "./BehaviorMetricsStrip";
import { ActivityTimeline } from "./ActivityTimeline";
import { applyAuthority } from "@/api/authority";
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
      const policy = insights.authorityPolicy;
      if (!policy?.decisionId) throw new Error("No authority decision to apply");
      return applyAuthority({
        decisionId: policy.decisionId,
        amount: policy.approvedAmount,
        disputeId: policy.disputeId,
      });
    },
    onSuccess: () => {
      toast.success("Goodwill posted");
      void queryClient.invalidateQueries({ queryKey: ["customer-insights", insights.customerId] });
      void queryClient.invalidateQueries({ queryKey: ["customer", insights.customerId] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Goodwill apply failed"),
  });

  return (
    <div className="space-y-200">
      <BehaviorMetricsStrip metrics={insights.metrics} />
      {insights.authorityPolicy && insights.authorityPolicy.status !== "none" ? (
        <AuthorityPolicyBlock
          policy={insights.authorityPolicy}
          className="rounded-large border border-border bg-surface !border-t"
          onApply={() => applyMut.mutate()}
          applying={applyMut.isPending}
        />
      ) : null}
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
