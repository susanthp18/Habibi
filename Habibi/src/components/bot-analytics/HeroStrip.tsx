import {
  Bot,
  ShieldCheck,
  AlertTriangle,
  MessageSquare,
  Timer,
  Smile,
  TrendingUp,
  HandCoins,
} from "lucide-react";
import type { Kpis } from "@/api/types/bot-analytics";
import { VOICE_TTFA_SLO_MS } from "@/lib/bot-analytics";
import { LivelineSpark } from "@/components/charts";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import type { StatTone } from "@/components/ui/stat-tile";

const SPARK: Record<StatTone, string> = {
  success: "#5b7f24",
  warning: "#e06c00",
  danger: "#e2483d",
  brand: "#1868db",
  info: "#1868db",
  discovery: "#1868db",
  neutral: "#1868db",
};

function spark(data: number[], tone: StatTone) {
  return (
    <div className="overflow-hidden rounded-medium bg-surface-sunken">
      <LivelineSpark data={data} color={SPARK[tone]} height={36} />
    </div>
  );
}

export function HeroStrip({ kpis }: { kpis: Kpis }) {
  const containment: StatTone =
    kpis.containment >= 80 ? "success" : kpis.containment >= 65 ? "warning" : "danger";
  const escalation: StatTone = kpis.escalation > 20 ? "danger" : "warning";
  const ptp: StatTone = kpis.ptpRate >= 15 ? "success" : "warning";
  const latency: StatTone = kpis.latencyP90 > VOICE_TTFA_SLO_MS ? "warning" : "success";
  const csat: StatTone = kpis.csatProxy >= 75 ? "success" : "warning";
  return (
    <MetricsStrip
      className="border-b border-border bg-surface px-250 py-150 md:grid-cols-4 xl:grid-cols-8"
      tiles={[
        {
          variant: "card",
          icon: ShieldCheck,
          label: "Containment",
          value: `${kpis.containment.toFixed(1)}%`,
          sub: `${kpis.sessions.toLocaleString()} sessions`,
          tone: containment,
          footer: spark(kpis.containmentSpark, containment),
        },
        {
          variant: "card",
          icon: Bot,
          label: "Deflection",
          value: `${kpis.deflection.toFixed(1)}%`,
          sub: "Resolved without human",
          footer: spark(kpis.sessionsSpark, "brand"),
        },
        {
          variant: "card",
          icon: AlertTriangle,
          label: "Escalation",
          value: `${kpis.escalation.toFixed(1)}%`,
          sub: `Abandon ${kpis.abandonment.toFixed(1)}%`,
          tone: escalation,
          footer: spark(kpis.escalationSpark, escalation),
        },
        {
          variant: "card",
          icon: TrendingUp,
          label: "Upsell presented",
          value: `${kpis.upsellRate.toFixed(1)}%`,
          sub: "Sessions with offer",
          footer: spark(kpis.upsellSpark, "brand"),
        },
        {
          variant: "card",
          icon: HandCoins,
          label: "PTP rate",
          value: `${kpis.ptpRate.toFixed(1)}%`,
          sub: "Promise-to-pay captured",
          tone: ptp,
          footer: spark(kpis.ptpSpark, ptp),
        },
        {
          variant: "card",
          icon: MessageSquare,
          label: "Avg turns",
          value: kpis.avgTurns.toFixed(1),
          sub: "Per resolved session",
          footer: spark(kpis.turnsSpark, "brand"),
        },
        {
          variant: "card",
          icon: Timer,
          label: "Latency p90",
          value: `${(kpis.latencyP90 / 1000).toFixed(2)}s`,
          sub: `p50 ${(kpis.latencyP50 / 1000).toFixed(2)}s · SLO ${VOICE_TTFA_SLO_MS}ms`,
          tone: latency,
          footer: spark(kpis.latencySpark, latency),
        },
        {
          variant: "card",
          icon: Smile,
          label: "CSAT proxy",
          value: kpis.csatProxy.toFixed(0),
          sub: `Sent ${kpis.avgSentiment.toFixed(2)}`,
          tone: csat,
          footer: spark(kpis.sentimentSpark, csat),
        },
      ]}
    />
  );
}
