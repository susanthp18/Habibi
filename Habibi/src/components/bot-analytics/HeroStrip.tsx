import { LineChart, Line, ResponsiveContainer } from "recharts";
import { Bot, ShieldCheck, AlertTriangle, MessageSquare, Timer, Smile, TrendingUp, HandCoins } from "lucide-react";
import type { Kpis } from "@/data/bot-analytics-seed";

function Spark({ data, color = "var(--background-brand-bold)" }: { data: number[]; color?: string }) {
  return (
    <div className="h-400 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data.map((v, i) => ({ i, v }))} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  hint,
  spark,
  tone,
}: {
  icon: any;
  label: string;
  value: string;
  hint?: string;
  spark: number[];
  tone?: string;
}) {
  return (
    <div className="min-w-[11.25rem] flex-1 rounded-large border border-border bg-surface px-150 py-150">
      <div className="flex items-center gap-075 text-body-small font-medium text-text-subtlest">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className={`mt-025 text-[1.5rem] font-semibold ${tone ?? "text-text"}`}>{value}</div>
      {hint && <div className="text-body-small text-text-subtlest">{hint}</div>}
      <Spark data={spark} color={tone?.includes("red") ? "#E2483D" : tone?.includes("amber") ? "#F68909" : tone?.includes("emerald") ? "#82B536" : "var(--background-brand-bold)"} />
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
          tone={kpis.containment >= 80 ? "text-text-success-bolder" : kpis.containment >= 65 ? "text-text-warning-bolder" : "text-text-danger-bolder"}
        />
        <Tile
          icon={Bot}
          label="Deflection"
          value={`${kpis.deflection.toFixed(1)}%`}
          hint="Resolved without human"
          spark={kpis.sessionsSpark}
        />
        <Tile
          icon={AlertTriangle}
          label="Escalation"
          value={`${kpis.escalation.toFixed(1)}%`}
          hint={`Abandon ${kpis.abandonment.toFixed(1)}%`}
          spark={kpis.escalationSpark}
          tone={kpis.escalation > 20 ? "text-text-danger-bolder" : "text-text-warning-bolder"}
        />
        <Tile
          icon={TrendingUp}
          label="Upsell presented"
          value={`${kpis.upsellRate.toFixed(1)}%`}
          hint="Sessions with offer"
          spark={kpis.upsellSpark}
        />
        <Tile
          icon={HandCoins}
          label="PTP rate"
          value={`${kpis.ptpRate.toFixed(1)}%`}
          hint="Promise-to-pay captured"
          spark={kpis.ptpSpark}
          tone={kpis.ptpRate >= 15 ? "text-text-success-bolder" : "text-text-warning-bolder"}
        />
        <Tile
          icon={MessageSquare}
          label="Avg turns"
          value={kpis.avgTurns.toFixed(1)}
          hint="Per resolved session"
          spark={kpis.turnsSpark}
        />
        <Tile
          icon={Timer}
          label="Latency p90"
          value={`${(kpis.latencyP90 / 1000).toFixed(2)}s`}
          hint={`p50 ${(kpis.latencyP50 / 1000).toFixed(2)}s`}
          spark={kpis.latencySpark}
          tone={kpis.latencyP90 > 1500 ? "text-text-warning-bolder" : "text-text-success-bolder"}
        />
        <Tile
          icon={Smile}
          label="CSAT proxy"
          value={`${kpis.csatProxy.toFixed(0)}`}
          hint={`Sent ${kpis.avgSentiment.toFixed(2)}`}
          spark={kpis.sentimentSpark}
          tone={kpis.csatProxy >= 75 ? "text-text-success-bolder" : "text-text-warning-bolder"}
        />
      </div>
    </div>
  );
}
