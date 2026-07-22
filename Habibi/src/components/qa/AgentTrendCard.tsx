import { LineChart, Line, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer, Tooltip } from "recharts";
import type { AgentQaStat } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";

export function AgentTrendCard({ stat }: { stat: AgentQaStat | null }) {
  if (!stat) {
    return (
      <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-6 text-center text-[12px] text-text-muted">
        Select an agent to view their trend.
      </div>
    );
  }
  const trendData = stat.trend.map((v, i) => ({ day: `D${i + 1}`, v }));
  const radar = stat.sectionScores.map((s) => ({ subject: s.section, A: s.value }));

  return (
    <div className="space-y-3 rounded-lg border border-[var(--border-token)] bg-surface-card p-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[14px] font-semibold text-brand-navy">{stat.agentId}</div>
          <div className="text-[11px] text-text-muted">{stat.scored} scorecards · weakest: {stat.weakestSection}</div>
        </div>
        <ScoreBand total={stat.avg} size="md" />
      </div>

      <div>
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">7-day score trend</div>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} labelStyle={{ display: "none" }} />
              <Line type="monotone" dataKey="v" stroke="var(--brand-primary)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">Section breakdown</div>
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={radar} outerRadius="72%">
              <PolarGrid stroke="var(--border-token)" />
              <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
              <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
              <Radar dataKey="A" stroke="var(--brand-primary)" fill="var(--brand-primary)" fillOpacity={0.25} />
              <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
