import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import type { TurnsBucket } from "@/data/bot-analytics-seed";

const COLORS = ["#10b981", "#22c55e", "#f59e0b", "#f97316", "#dc2626"];

export function TurnsHistogram({ buckets }: { buckets: TurnsBucket[] }) {
  const data = buckets.map((b) => ({ label: b.label, count: b.count }));
  const total = data.reduce((a, b) => a + b.count, 0);
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[13px] font-semibold text-brand-navy">Turns to resolution</div>
        <div className="text-[11px] text-text-muted">{total.toLocaleString()} sessions · fewer turns = better</div>
      </div>
      <div className="h-56 p-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-token)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
            <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
            <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
