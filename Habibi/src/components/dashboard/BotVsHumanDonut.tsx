import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

type Slice = { name: string; value: number; color: string };

export function BotVsHumanDonut({ data }: { data: Slice[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const contained = data.find((d) => d.name === "Contained by bot")?.value ?? 0;
  const containment = total ? (contained / total) * 100 : 0;

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface-card p-4 shadow-card">
      <div className="mb-2">
        <h3 className="text-sm font-semibold text-brand-navy">Bot vs Human handling</h3>
        <p className="text-xs text-text-secondary">How every call ended up being resolved</p>
      </div>
      <div className="flex min-h-0 flex-1 items-center gap-4">
        <div className="relative h-40 w-40 shrink-0">
          <ResponsiveContainer>
            <PieChart>
              <Tooltip
                contentStyle={{
                  background: "var(--surface-card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v: number, n) => [`${v.toLocaleString()} calls`, n as string]}
              />
              <Pie data={data} innerRadius={44} outerRadius={70} paddingAngle={2} dataKey="value" stroke="none">
                {data.map((s) => (
                  <Cell key={s.name} fill={s.color} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <div className="text-xl font-semibold text-brand-navy tabular">{containment.toFixed(0)}%</div>
            <div className="text-[10px] uppercase tracking-wide text-text-secondary">Containment</div>
          </div>
        </div>
        <ul className="flex-1 space-y-2">
          {data.map((s) => {
            const pct = total ? ((s.value / total) * 100).toFixed(1) : "0";
            return (
              <li key={s.name} className="flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
                  <span className="text-text-primary">{s.name}</span>
                </span>
                <span className="tabular text-text-secondary">
                  {s.value.toLocaleString()} · {pct}%
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
