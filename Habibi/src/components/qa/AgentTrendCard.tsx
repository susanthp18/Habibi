import { LineChart, Line, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer, Tooltip } from "recharts";
import type { AgentQaStat } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";

export function AgentTrendCard({ stat }: { stat: AgentQaStat | null }) {
  if (!stat) {
    return (
      <div className="rounded-large border border-border bg-surface p-300 text-center text-body-small text-text-subtlest">
        Select an agent to view their trend.
      </div>
    );
  }
  const trendData = stat.trend.map((v, i) => ({ day: `D${i + 1}`, v }));
  const radar = stat.sectionScores.map((s) => ({ subject: s.section, A: s.value }));

  return (
    <div className="space-y-150 rounded-large border border-border bg-surface p-150">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-body font-semibold text-text">{stat.agentId}</div>
          <div className="text-body-small text-text-subtlest">{stat.scored} scorecards · weakest: {stat.weakestSection}</div>
        </div>
        <ScoreBand total={stat.avg} size="md" />
      </div>

      <div>
        <div className="mb-050 text-body-small font-medium text-text-subtlest">7-day score trend</div>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} labelStyle={{ display: "none" }} />
              <Line type="monotone" dataKey="v" stroke="var(--background-brand-bold)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <div className="mb-050 text-body-small font-medium text-text-subtlest">Section breakdown</div>
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={radar} outerRadius="72%">
              <PolarGrid stroke="var(--border)" />
              <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
              <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
              <Radar dataKey="A" stroke="var(--background-brand-bold)" fill="var(--background-brand-bold)" fillOpacity={0.25} />
              <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
