import { InsightsPanel } from "./InsightsPanel";
import { NextBestActionCard } from "./NextBestActionCard";
import { BehaviorMetricsStrip } from "./BehaviorMetricsStrip";
import { ActivityTimeline } from "./ActivityTimeline";
import type { CustomerInsights, NbaActionKind } from "@/lib/customerInsights";

export function OverviewTab({
  insights,
  onNbaAction,
}: {
  insights: CustomerInsights;
  onNbaAction: (action: NbaActionKind) => void;
}) {
  return (
    <div className="space-y-200">
      <BehaviorMetricsStrip metrics={insights.metrics} />
      <div className="grid gap-200 lg:grid-cols-2">
        <InsightsPanel bullets={insights.summary} />
        <NextBestActionCard items={insights.nba} onAction={onNbaAction} />
      </div>
      <ActivityTimeline items={insights.activity} />
    </div>
  );
}
