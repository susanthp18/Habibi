import {
  ArrowDownRight,
  ArrowUpRight,
  PhoneCall,
  Clock,
  CheckCircle2,
  HandCoins,
} from "lucide-react";
import { useWorkspaceSummary } from "@/api/workspace";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

function delta(text: string, good: boolean, invertArrow = false) {
  const Arrow = (invertArrow ? !good : good) ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-050 rounded-medium px-075 py-025 text-body-small font-medium",
        good ? "bg-background-success text-text-success" : "bg-background-danger text-text-danger",
      )}
    >
      <Arrow className="h-3.5 w-3.5" />
      <span>{text}</span>
    </span>
  );
}

/**
 * Rolling 7-day aggregates from GET /workspace/summary (anchored to latest
 * interaction date so historical seed isn't all-zero).
 */
export function StatsStrip() {
  const { data } = useWorkspaceSummary("me");
  const stats = data?.stats;

  const ahtDelta = stats?.ahtDelta ?? "—";
  const ahtImproved = /^-/.test(ahtDelta.trim());
  const callsDelta = stats?.callsHandledDelta ?? "—";

  return (
    <div>
      {stats?.windowLabel && (
        <div className="mb-100 inline-flex items-center rounded-medium bg-surface-sunken px-100 py-025 text-body-small font-medium text-text-subtlest">
          {stats.windowLabel}
        </div>
      )}
      <MetricsStrip
        className="gap-150 md:grid-cols-4"
        tiles={[
          {
            variant: "card",
            label: "Calls handled",
            value: stats?.callsHandled ?? 0,
            icon: PhoneCall,
            footer: delta(callsDelta, !/^-/.test(callsDelta.trim())),
          },
          {
            variant: "card",
            label: "Avg handle time",
            value: stats?.aht ?? "—",
            icon: Clock,
            footer: delta(ahtDelta, ahtImproved, true),
          },
          {
            variant: "card",
            label: "Resolutions",
            value: stats?.resolutions ?? 0,
            icon: CheckCircle2,
            footer: delta(`${stats?.resolutionRate ?? "0%"} rate`, true),
          },
          {
            variant: "card",
            label: "Promises captured",
            value: stats?.promisesCount ?? 0,
            icon: HandCoins,
            footer: delta(inr(Math.round(stats?.promisesAmount ?? 0)), true),
          },
        ]}
      />
    </div>
  );
}
