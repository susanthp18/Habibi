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
    <div className="flex h-full min-h-[17.5rem] flex-col rounded-large border border-border bg-surface p-200">
      <div className="mb-100 shrink-0">
        <h3 className="text-body font-semibold text-text">Share by category</h3>
        <p className="text-body-small text-text-subtle">LLM · Voice · Messaging · Infra</p>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-150">
        <div className="mx-auto h-44 w-full max-w-[13.75rem]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
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
        <div className="space-y-075 text-body-small">
          {rows.map((r) => {
            const pct = grand > 0 ? Math.round((r.value / grand) * 100) : 0;
            return (
              <div key={r.name} className="flex items-center gap-100">
                <span className="h-2.5 w-2.5 shrink-0 rounded-small" style={{ backgroundColor: r.color }} />
                <span className="flex-1 font-medium text-text">{r.name}</span>
                <span className="font-mono text-text-subtle">{inrCompact(r.value)}</span>
                <span className="w-400 text-right text-body-small text-text-subtlest">{pct}%</span>
              </div>
            );
          })}
          {rows.length === 0 && (
            <p className="text-body-small text-text-subtlest">No spend in this period.</p>
          )}
        </div>
      </div>
    </div>
  );
}
