import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { escalationReasons } from "@/data/bot-analytics-seed";

const COLORS = ["#2563eb", "#0ea5e9", "#06b6d4", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"];

export function EscalationReasons() {
  const total = escalationReasons.reduce((a, r) => a + r.count, 0);
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[13px] font-semibold text-brand-navy">Escalation reasons</div>
        <div className="text-[11px] text-text-muted">{total.toLocaleString()} escalations · trend vs prior period</div>
      </div>
      <div className="grid gap-3 p-3 md:grid-cols-[180px_1fr]">
        <div className="h-44">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={escalationReasons} dataKey="count" nameKey="label" innerRadius="55%" outerRadius="90%" paddingAngle={2}>
                {escalationReasons.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 11, padding: "4px 6px" }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="space-y-1 text-[12px]">
          {escalationReasons.map((r, i) => {
            const pct = (r.count / total) * 100;
            const Trend = r.trendDelta > 1 ? ArrowUp : r.trendDelta < -1 ? ArrowDown : Minus;
            const bad = r.trendDelta > 1;
            return (
              <li key={r.id} className="flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="flex-1 truncate text-text-primary">{r.label}</span>
                <span className="text-text-secondary tabular-nums">{r.count}</span>
                <span className="w-10 text-right text-text-muted tabular-nums">{pct.toFixed(0)}%</span>
                <span className={`inline-flex w-14 items-center justify-end gap-0.5 text-[11px] ${bad ? "text-red-700" : r.trendDelta < -1 ? "text-emerald-700" : "text-text-muted"}`}>
                  <Trend className="h-3 w-3" />
                  {Math.abs(r.trendDelta)}%
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
