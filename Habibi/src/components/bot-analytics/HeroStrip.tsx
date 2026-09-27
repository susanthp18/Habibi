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

const NONE = "—";
const pct = (v: number | null) => (v == null ? NONE : `${v.toFixed(1)}%`);
const secs = (ms: number | null) => (ms == null ? NONE : `${(ms / 1000).toFixed(2)}s`);

export function HeroStrip({ kpis }: { kpis: Kpis }) {
  const containment: StatTone =
    kpis.containment == null
      ? "neutral"
      : kpis.containment >= 80
        ? "success"
        : kpis.containment >= 65
          ? "warning"
          : "danger";
  const escalation: StatTone = kpis.escalation > 20 ? "danger" : "warning";
  const ptp: StatTone = kpis.ptpRate >= 15 ? "success" : "warning";
  const latency: StatTone =
    kpis.latencyP90 == null
      ? "neutral"
      : kpis.latencyP90 > VOICE_TTFA_SLO_MS
        ? "warning"
        : "success";
  const lift: StatTone =
    kpis.sentimentLift == null ? "neutral" : kpis.sentimentLift >= 0 ? "success" : "warning";
  return (
    <MetricsStrip
      className="border-b border-border bg-surface px-250 py-150 md:grid-cols-4 xl:grid-cols-8"
      tiles={[
        {
          variant: "card",
          icon: ShieldCheck,
          label: "Containment",
          value: pct(kpis.containment),
          sub: (
            <span title="Bot sessions never handed to a human, over all bot sessions in range.">
              {kpis.sessions.toLocaleString()} sessions · no human handoff
            </span>
          ),
          tone: containment,
          footer: spark(kpis.containmentSpark, containment),
        },
        {
          variant: "card",
          icon: Bot,
          label: "Deflection",
          value: pct(kpis.deflection),
          sub: (
            <span
              title={`Inbound bot sessions resolved with no human handoff and no repeat contact from the customer within ${kpis.repeatContactDays} days. Only sessions at least ${kpis.repeatContactDays} days old count.`}
            >
              {kpis.deflectionEligible
                ? `No human, no repeat in ${kpis.repeatContactDays}d · ${kpis.deflectionEligible} inbound`
                : `Needs inbound sessions ${kpis.repeatContactDays}+ days old`}
            </span>
          ),
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
          value: secs(kpis.latencyP90),
          sub: `p50 ${secs(kpis.latencyP50)} · SLO ${VOICE_TTFA_SLO_MS}ms · over calls`,
          tone: latency,
          footer: spark(kpis.latencySpark, latency),
        },
        {
          variant: "card",
          icon: Smile,
          label: "Sentiment lift",
          value:
            kpis.sentimentLift == null
              ? NONE
              : `${kpis.sentimentLift > 0 ? "+" : ""}${kpis.sentimentLift.toFixed(2)}`,
          sub: (
            <span title="Per call: the customer's last sentiment minus their first (scale -1 to 1, so -2 to +2), averaged over calls with at least two readings. Positive means callers ended happier than they started.">
              {kpis.sentimentLiftCalls
                ? `Last − first customer turn · ${kpis.sentimentLiftCalls} calls`
                : "No sentiment signals in range"}
            </span>
          ),
          tone: lift,
          footer: spark(kpis.sentimentSpark, lift),
        },
      ]}
    />
  );
}
