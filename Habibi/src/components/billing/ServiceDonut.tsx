import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { CATEGORY_COLORS, SERVICES, sumRange, inrCompact, type DayPoint, type ServiceCategory } from "@/data/billing-seed";

export function ServiceDonut({ data }: { data: DayPoint[] }) {
  const totals: Record<ServiceCategory, number> = { LLM: 0, Voice: 0, Messaging: 0, Infra: 0 };
  for (const s of SERVICES) {
    totals[s.category] += sumRange(data, s.id);
  }
  const rows = (Object.keys(totals) as ServiceCategory[]).map((k) => ({
    name: k,
    value: totals[k],
    color: CATEGORY_COLORS[k],
  }));
  const grand = rows.reduce((a, r) => a + r.value, 0);

  return (
    <div className="flex h-full min-h-[280px] flex-col rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
      <div className="mb-2">
        <h3 className="text-[13px] font-semibold text-brand-navy">Share by category</h3>
        <p className="text-[11px] text-text-secondary">LLM · Voice · Messaging · Infra</p>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-3">
        <div className="min-h-[200px]">
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
                innerRadius={45}
                outerRadius={70}
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
        <div className="flex flex-col justify-center gap-2 text-[12px]">
          {rows.map((r) => {
            const pct = grand > 0 ? Math.round((r.value / grand) * 100) : 0;
            return (
              <div key={r.name} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: r.color }} />
                <span className="flex-1 font-medium text-brand-navy">{r.name}</span>
                <span className="font-mono text-text-secondary">{inrCompact(r.value)}</span>
                <span className="w-8 text-right text-[10.5px] text-text-muted">{pct}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
