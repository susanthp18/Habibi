import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import {
  CATEGORY_COLORS,
  sumRange,
  inrCompact,
  type DayPoint,
  type Service,
  type ServiceCategory,
} from "@/data/billing-seed";

export function ServiceDonut({ data, services }: { data: DayPoint[]; services: Service[] }) {
  const totals: Record<ServiceCategory, number> = { LLM: 0, Voice: 0, Messaging: 0, Infra: 0 };
  for (const s of services) {
    totals[s.category] += sumRange(data, s.id);
  }
  const rows = (Object.keys(totals) as ServiceCategory[])
    .map((k) => ({
      name: k,
      value: totals[k],
      color: CATEGORY_COLORS[k],
    }))
    .filter((r) => r.value > 0);
  const grand = rows.reduce((a, r) => a + r.value, 0);

  return (
    <div className="flex h-full min-h-[280px] flex-col rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
      <div className="mb-2 shrink-0">
        <h3 className="text-[13px] font-semibold text-brand-navy">Share by category</h3>
        <p className="text-[11px] text-text-secondary">LLM · Voice · Messaging · Infra</p>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="mx-auto h-44 w-full max-w-[220px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  borderRadius: 8,
                  border: "1px solid var(--border-token)",
                  background: "var(--surface-card)",
                }}
                formatter={(v: number) => inrCompact(v)}
              />
              <Pie
                data={rows}
                dataKey="value"
                innerRadius="55%"
                outerRadius="80%"
                paddingAngle={2}
                stroke="none"
              >
                {rows.map((r) => (
                  <Cell key={r.name} fill={r.color} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="space-y-1.5 text-[12px]">
          {rows.map((r) => {
            const pct = grand > 0 ? Math.round((r.value / grand) * 100) : 0;
            return (
              <div key={r.name} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: r.color }} />
                <span className="flex-1 font-medium text-brand-navy">{r.name}</span>
                <span className="font-mono text-text-secondary">{inrCompact(r.value)}</span>
                <span className="w-8 text-right text-[10.5px] text-text-muted">{pct}%</span>
              </div>
            );
          })}
          {rows.length === 0 && (
            <p className="text-[11.5px] text-text-muted">No spend in this period.</p>
          )}
        </div>
      </div>
    </div>
  );
}
