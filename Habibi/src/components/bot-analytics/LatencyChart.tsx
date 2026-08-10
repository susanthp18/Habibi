import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from "recharts";
import type { DailyPoint } from "@/data/bot-analytics-seed";

export function LatencyChart({ points }: { points: DailyPoint[] }) {
  const data = points.map((p) => ({
    date: p.date.slice(5),
    p50: Math.round(p.latencyP50),
    p90: Math.round(p.latencyP90),
    p99: Math.round(p.latencyP99),
  }));
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-150 py-100">
        <div className="text-body font-semibold text-text">Response latency</div>
        <div className="text-body-small text-text-subtlest">p50 / p90 / p99 in ms</div>
      </div>
      <div className="h-56 p-150">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-secondary)" }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
            <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="p50" stroke="#82B536" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="p90" stroke="#F68909" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="p99" stroke="#E2483D" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
