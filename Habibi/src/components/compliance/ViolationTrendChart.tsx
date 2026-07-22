import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { trendByDay, type Violation } from "@/data/compliance-seed";

export function ViolationTrendChart({ all }: { all: Violation[] }) {
  const data = trendByDay(all, 30);
  return (
    <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <div>
          <div className="text-[13px] font-semibold text-brand-navy">Violation trend</div>
          <div className="text-[11px] text-text-muted">Last 30 days · stacked by severity</div>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-text-secondary">
          <Legend color="var(--danger)" label="Critical" />
          <Legend color="var(--warning)" label="High" />
          <Legend color="var(--sentiment-neutral)" label="Medium" />
          <Legend color="var(--text-muted)" label="Low" />
        </div>
      </div>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="var(--border-token)" strokeDasharray="2 3" vertical={false} />
            <XAxis dataKey="day" tick={{ fontSize: 10, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip
              contentStyle={{
                background: "var(--surface-card)",
                border: "1px solid var(--border-token)",
                borderRadius: 6,
                fontSize: 12,
              }}
              labelStyle={{ color: "var(--brand-navy)", fontWeight: 600 }}
            />
            <Area type="monotone" dataKey="low" stackId="1" stroke="var(--text-muted)" fill="var(--text-muted)" fillOpacity={0.25} />
            <Area type="monotone" dataKey="medium" stackId="1" stroke="var(--sentiment-neutral)" fill="var(--sentiment-neutral)" fillOpacity={0.35} />
            <Area type="monotone" dataKey="high" stackId="1" stroke="var(--warning)" fill="var(--warning)" fillOpacity={0.45} />
            <Area type="monotone" dataKey="critical" stackId="1" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.55} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
