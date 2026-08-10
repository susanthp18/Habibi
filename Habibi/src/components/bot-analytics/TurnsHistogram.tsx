import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import type { TurnsBucket } from "@/data/bot-analytics-seed";

const COLORS = ["#82B536", "#5B7F24", "#F68909", "#BD5B00", "#E2483D"];

export function TurnsHistogram({ buckets }: { buckets: TurnsBucket[] }) {
  const data = buckets.map((b) => ({ label: b.label, count: b.count }));
  const total = data.reduce((a, b) => a + b.count, 0);
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-150 py-100">
        <div className="text-body font-semibold text-text">Turns to resolution</div>
        <div className="text-body-small text-text-subtlest">{total.toLocaleString()} sessions · fewer turns = better</div>
      </div>
      <div className="h-56 p-150">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
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
