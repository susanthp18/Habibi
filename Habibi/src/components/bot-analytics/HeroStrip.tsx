import { Bot, ShieldCheck, AlertTriangle, MessageSquare, Timer, Smile, TrendingUp, HandCoins } from "lucide-react";
import type { Kpis } from "@/data/bot-analytics-seed";
import { VOICE_TTFA_SLO_MS } from "@/data/bot-analytics-seed";
import { LivelineSpark } from "@/components/charts";

function Tile({
  icon: Icon,
  label,
  value,
  hint,
  spark,
  tone,
  sparkColor,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
  spark: number[];
  tone?: string;
  sparkColor: string;
}) {
  return (
    <div className="min-w-[11.25rem] flex-1 rounded-large border border-border bg-surface px-150 py-150 shadow-raised">
      <div className="flex items-center gap-075 text-body-small font-medium text-text-subtlest">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className={`mt-025 text-[1.5rem] font-semibold tracking-tight tabular-nums ${tone ?? "text-text"}`}>{value}</div>
      {hint && <div className="text-body-small text-text-subtlest">{hint}</div>}
      <div className="mt-075 overflow-hidden rounded-medium bg-surface-sunken">
        <LivelineSpark data={spark} color={sparkColor} height={36} />
      </div>
    </div>
  );
}

export function HeroStrip({ kpis }: { kpis: Kpis }) {
  return (
    <div className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap gap-100">
        <Tile
          icon={ShieldCheck}
          label="Containment"
          value={`${kpis.containment.toFixed(1)}%`}
          hint={`${kpis.sessions.toLocaleString()} sessions`}
          spark={kpis.containmentSpark}
          sparkColor={kpis.containment >= 80 ? "#5b7f24" : kpis.containment >= 65 ? "#e06c00" : "#e2483d"}
          tone={kpis.containment >= 80 ? "text-text-success-bolder" : kpis.containment >= 65 ? "text-text-warning-bolder" : "text-text-danger-bolder"}
        />
        <Tile
          icon={Bot}
          label="Deflection"
          value={`${kpis.deflection.toFixed(1)}%`}
          hint="Resolved without human"
          spark={kpis.sessionsSpark}
          sparkColor="#1868db"
        />
        <Tile
          icon={AlertTriangle}
          label="Escalation"
          value={`${kpis.escalation.toFixed(1)}%`}
          hint={`Abandon ${kpis.abandonment.toFixed(1)}%`}
          spark={kpis.escalationSpark}
          sparkColor={kpis.escalation > 20 ? "#e2483d" : "#e06c00"}
          tone={kpis.escalation > 20 ? "text-text-danger-bolder" : "text-text-warning-bolder"}
        />
        <Tile
          icon={TrendingUp}
          label="Upsell presented"
          value={`${kpis.upsellRate.toFixed(1)}%`}
          hint="Sessions with offer"
          spark={kpis.upsellSpark}
          sparkColor="#1868db"
        />
        <Tile
          icon={HandCoins}
          label="PTP rate"
          value={`${kpis.ptpRate.toFixed(1)}%`}
          hint="Promise-to-pay captured"
          spark={kpis.ptpSpark}
          sparkColor={kpis.ptpRate >= 15 ? "#5b7f24" : "#e06c00"}
          tone={kpis.ptpRate >= 15 ? "text-text-success-bolder" : "text-text-warning-bolder"}
        />
        <Tile
          icon={MessageSquare}
          label="Avg turns"
          value={kpis.avgTurns.toFixed(1)}
          hint="Per resolved session"
          spark={kpis.turnsSpark}
          sparkColor="#1868db"
        />
        <Tile
          icon={Timer}
          label="Latency p90"
          value={`${(kpis.latencyP90 / 1000).toFixed(2)}s`}
          hint={`p50 ${(kpis.latencyP50 / 1000).toFixed(2)}s · SLO ${VOICE_TTFA_SLO_MS}ms`}
          spark={kpis.latencySpark}
          sparkColor={kpis.latencyP90 > VOICE_TTFA_SLO_MS ? "#e06c00" : "#5b7f24"}
          tone={kpis.latencyP90 > VOICE_TTFA_SLO_MS ? "text-text-warning-bolder" : "text-text-success-bolder"}
        />
        <Tile
          icon={Smile}
          label="CSAT proxy"
          value={`${kpis.csatProxy.toFixed(0)}`}
          hint={`Sent ${kpis.avgSentiment.toFixed(2)}`}
          spark={kpis.sentimentSpark}
          sparkColor={kpis.csatProxy >= 75 ? "#5b7f24" : "#e06c00"}
          tone={kpis.csatProxy >= 75 ? "text-text-success-bolder" : "text-text-warning-bolder"}
        />
      </div>
    </div>
  );
}
