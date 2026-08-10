import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Trend } from "@/data/dashboard-seed";

function fmtDate(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Indian money conventions — these are INR balances off `ledger_entries`, and
// the chart rendered them with a dollar sign and Western magnitudes.
function fmtMoney(n: number) {
  if (Math.abs(n) >= 10_000_000) return `₹${(n / 10_000_000).toFixed(1)} Cr`;
  if (Math.abs(n) >= 100_000) return `₹${(n / 100_000).toFixed(1)} L`;
  if (Math.abs(n) >= 1_000) return `₹${(n / 1_000).toFixed(0)}K`;
  return `₹${n.toFixed(0)}`;
}

export function RecoveryTrendChart({ data }: { data: Trend[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="flex h-full flex-col rounded-large border border-border bg-surface p-200">
      <div className="mb-100 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">Recovery over time</h3>
          <p className="text-xs text-text-subtle">Payments posted in the selected period</p>
        </div>
        <div className="text-right">
          <div className="text-xs text-text-subtle">Period total</div>
          <div className="text-sm font-semibold text-text tabular">{fmtMoney(total)}</div>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {data.length === 0 ? (
          // The series is a real query now, so "no payments in this range" is a
          // legitimate answer. Rendering an empty axis instead read as broken.
          <div className="flex h-full min-h-[200px] items-center justify-center text-body-small text-text-subtle">
            No payments recorded in this period.
          </div>
        ) : (
        <ResponsiveContainer width="100%" height="100%" minHeight={200}>
          <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="recoveryFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--background-brand-bold)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--background-brand-bold)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={fmtDate}
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              axisLine={false}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={fmtMoney}
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={(v) => fmtDate(String(v))}
              formatter={(v: number) => [fmtMoney(v), "Recovered"]}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="var(--background-brand-bold)"
              strokeWidth={2}
              fill="url(#recoveryFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
