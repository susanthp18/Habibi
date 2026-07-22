import { LineChart, Line, ResponsiveContainer } from "recharts";
import { Bot, ShieldCheck, AlertTriangle, MessageSquare, Timer, Smile } from "lucide-react";
import type { Kpis } from "@/data/bot-analytics-seed";

function Spark({ data, color = "var(--brand-primary)" }: { data: number[]; color?: string }) {
  return (
    <div className="h-8 w-full">
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
    <div className="min-w-[180px] flex-1 rounded-lg border border-[var(--border-token)] bg-surface-card px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className={`mt-0.5 text-[22px] font-semibold ${tone ?? "text-brand-navy"}`}>{value}</div>
      {hint && <div className="text-[11px] text-text-muted">{hint}</div>}
      <Spark data={spark} color={tone?.includes("red") ? "#dc2626" : tone?.includes("amber") ? "#d97706" : tone?.includes("emerald") ? "#059669" : "var(--brand-primary)"} />
    </div>
  );
}

export function HeroStrip({ kpis }: { kpis: Kpis }) {
  return (
    <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-app px-5 py-3">
      <div className="flex flex-wrap gap-2">
        <Tile
          icon={ShieldCheck}
          label="Containment"
          value={`${kpis.containment.toFixed(1)}%`}
          hint={`${kpis.sessions.toLocaleString()} sessions`}
          spark={kpis.containmentSpark}
          tone={kpis.containment >= 80 ? "text-emerald-700" : kpis.containment >= 65 ? "text-amber-700" : "text-red-700"}
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
          tone={kpis.escalation > 20 ? "text-red-700" : "text-amber-700"}
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
          tone={kpis.latencyP90 > 1500 ? "text-amber-700" : "text-emerald-700"}
        />
        <Tile
          icon={Smile}
          label="CSAT proxy"
          value={`${kpis.csatProxy.toFixed(0)}`}
          hint={`Sent ${kpis.avgSentiment.toFixed(2)}`}
          spark={kpis.sentimentSpark}
          tone={kpis.csatProxy >= 75 ? "text-emerald-700" : "text-amber-700"}
        />
      </div>
    </div>
  );
}
