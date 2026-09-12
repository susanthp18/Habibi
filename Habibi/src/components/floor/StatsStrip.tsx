import { Activity, AlertTriangle, Bot, Clock, PhoneCall, Users } from "lucide-react";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import type { FloorStats } from "@/api/floor";

export type FloorFocus = "all" | "critical" | "queue" | "bot-risk" | "human";

const fmtWait = (s: number) => {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
};

const signed = (n: number) => (n >= 0 ? `+${n.toFixed(2)}` : n.toFixed(2));

const LIVE = <span className="h-1.5 w-1.5 pulse-dot rounded-full bg-background-success" />;

export function StatsStrip({
  stats,
  focus,
  onFocus,
}: {
  stats: FloorStats;
  focus: FloorFocus;
  onFocus: (next: FloorFocus) => void;
}) {
  const toggle = (key: FloorFocus) => onFocus(focus === key ? "all" : key);
  return (
    <MetricsStrip
      className="border-b border-border bg-surface px-200 py-150 md:grid-cols-4 xl:grid-cols-8"
      tiles={[
        {
          label: "Live now",
          value: stats.callsInProgress,
          icon: PhoneCall,
          tone: "brand",
          badge: LIVE,
          active: focus === "all",
          onClick: () => onFocus("all"),
        },
        {
          label: "Need you",
          value: stats.criticalAlerts,
          icon: AlertTriangle,
          tone: stats.criticalAlerts > 0 ? "danger" : "brand",
          active: focus === "critical",
          onClick: () => toggle("critical"),
        },
        {
          label: "Waiting",
          value: stats.queueDepth,
          icon: Activity,
          tone: stats.queueDepth > 0 ? "warning" : "brand",
          active: focus === "queue",
          onClick: () => toggle("queue"),
        },
        {
          label: "Longest wait",
          value: fmtWait(stats.longestWaitSec),
          icon: Clock,
          tone: stats.longestWaitSec > 120 ? "warning" : "brand",
          active: focus === "queue",
          onClick: () => toggle("queue"),
        },
        {
          label: "Agents free",
          value: stats.agentsAvailable,
          icon: Users,
          tone: "brand",
          onClick: () => onFocus("all"),
        },
        {
          label: "On a call",
          value: stats.agentsOnCall,
          icon: Users,
          tone: "brand",
          active: focus === "human",
          onClick: () => toggle("human"),
        },
        {
          label: "Bots at risk",
          value: stats.botAtRisk,
          icon: Bot,
          tone: stats.botAtRisk > 0 ? "warning" : "brand",
          active: focus === "bot-risk",
          onClick: () => toggle("bot-risk"),
        },
        {
          label: "Avg sentiment",
          value: signed(stats.avgSentiment),
          icon: Activity,
          tone: stats.avgSentiment < 0 ? "danger" : "brand",
          onClick: () => onFocus("all"),
        },
      ]}
    />
  );
}
