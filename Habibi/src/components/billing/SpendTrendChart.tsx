import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type DayPoint, type Service, inrCompact } from "@/data/billing-seed";

export function SpendTrendChart({ data, services }: { data: DayPoint[]; services: Service[] }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const rows = useMemo(
    () =>
      data.map((d) => {
        const row: Record<string, string | number> = { date: d.date };
        let total = 0;
        for (const s of services) {
          const v = d.values[s.id] ?? 0;
          row[s.id] = v;
          total += v;
        }
        row.total = total;
        return row;
      }),
    [data, services],
  );

  const fmtDay = (d: string) => {
    const dt = new Date(d);
    return dt.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
  };

  return (
    <div className="flex h-full min-h-[17.5rem] flex-col rounded-large border border-border bg-surface p-200">
      <div className="mb-100 flex items-start justify-between">
        <div>
          <h3 className="text-body font-semibold text-text">Spend trend</h3>
          <p className="text-body-small text-text-subtle">Daily cost stacked by service</p>
        </div>
        <div className="text-right">
          <div className="text-body-small text-text-subtlest">Period total</div>
          <div className="text-body font-semibold text-text">
            {inrCompact(rows.reduce((s, r) => s + (r.total as number), 0))}
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%" minHeight={220}>
          <AreaChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={fmtDay}
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={24}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              tickFormatter={(v: number) => inrCompact(v)}
              tickLine={false}
              axisLine={false}
              width={55}
            />
            <Tooltip
              contentStyle={{
                fontSize: 11,
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: "var(--surface)",
              }}
              labelFormatter={fmtDay}
              formatter={(v: number, name) => [inrCompact(v), name as string]}
            />
            <Legend
              wrapperStyle={{ fontSize: 10 }}
              onClick={(o) => {
                const dk = (o as { dataKey?: unknown }).dataKey;
                if (typeof dk !== "string") return;
                setHidden((prev) => {
                  const next = new Set(prev);
                  if (next.has(dk)) next.delete(dk);
                  else next.add(dk);
                  return next;
                });
              }}
            />
            {services.map((s) => (
              <Area
                key={s.id}
                type="monotone"
                dataKey={s.id}
                name={s.name}
                stackId="1"
                stroke={s.color}
                fill={s.color}
                fillOpacity={hidden.has(s.id) ? 0 : 0.45}
                strokeWidth={hidden.has(s.id) ? 0 : 1.2}
                hide={hidden.has(s.id)}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
