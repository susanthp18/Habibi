import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import type { EscalationReason } from "@/data/bot-analytics-seed";

const COLORS = ["#357DE8", "#82B536", "#BF63F3", "#F68909", "#1558BC", "#964AC0", "#42B2D7"];

export function EscalationReasons({ reasons }: { reasons: EscalationReason[] }) {
  const total = reasons.reduce((a, r) => a + r.count, 0);
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-150 py-100">
        <div className="text-body font-semibold text-text">Escalation reasons</div>
        <div className="text-body-small text-text-subtlest">{total.toLocaleString()} escalations · trend vs prior period</div>
      </div>
      <div className="grid gap-150 p-150 md:grid-cols-[180px_1fr]">
        <div className="h-44">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={reasons} dataKey="count" nameKey="label" innerRadius="55%" outerRadius="90%" paddingAngle={2}>
                {reasons.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="space-y-050 text-body-small">
          {reasons.map((r, i) => {
            const pct = total ? (r.count / total) * 100 : 0;
            const Trend = r.trendDelta > 1 ? ArrowUp : r.trendDelta < -1 ? ArrowDown : Minus;
            const bad = r.trendDelta > 1;
            return (
              <li key={r.id} className="flex items-center gap-100">
                <span className="inline-block h-2.5 w-2.5 rounded-small" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="flex-1 truncate text-text">{r.label}</span>
                <span className="text-text-subtle tabular-nums">{r.count}</span>
                <span className="w-500 text-right text-text-subtlest tabular-nums">{pct.toFixed(0)}%</span>
                <span className={`inline-flex w-14 items-center justify-end gap-025 text-body-small ${bad ? "text-text-danger-bolder" : r.trendDelta < -1 ? "text-text-success-bolder" : "text-text-subtlest"}`}>
                  <Trend className="h-3 w-3" />
                  {Math.abs(r.trendDelta)}%
                </span>
              </li>
            );
          })}
          {!reasons.length && (
            <li className="text-text-subtlest">No escalations in this range.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
