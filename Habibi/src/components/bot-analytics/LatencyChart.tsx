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
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[13px] font-semibold text-brand-navy">Response latency</div>
        <div className="text-[11px] text-text-muted">p50 / p90 / p99 in ms</div>
      </div>
      <div className="h-56 p-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-token)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-secondary)" }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
            <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="p50" stroke="#10b981" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="p90" stroke="#2563eb" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="p99" stroke="#dc2626" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
