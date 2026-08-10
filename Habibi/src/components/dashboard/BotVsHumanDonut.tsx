import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

type Slice = { name: string; value: number; color: string };

/** Map retired / overly bright tokens onto Design.md bold chart colors. */
const COLOR_ALIASES: Record<string, string> = {
  "var(--brand-primary)": "var(--background-brand-bold)",
  "var(--brand-navy)": "var(--chart-gray-bold)",
  "var(--success)": "var(--chart-success-bold)",
  "var(--warning)": "var(--chart-warning-bold)",
  "var(--chart-brand)": "var(--background-brand-bold)",
  "var(--chart-success)": "var(--chart-success-bold)",
  "var(--chart-warning)": "var(--chart-warning-bold)",
  "var(--background-brand-boldest)": "var(--chart-gray-bold)",
};

function resolveColor(color: string, index: number) {
  if (COLOR_ALIASES[color]) return COLOR_ALIASES[color];
  if (color.startsWith("var(--") || color.startsWith("#")) return color;
  // Distinct fallbacks if an unknown token still slips through
  const fallbacks = [
    "var(--background-brand-bold)",
    "var(--chart-warning-bold)",
    "var(--chart-gray-bold)",
  ];
  return fallbacks[index % fallbacks.length];
}

export function BotVsHumanDonut({ data }: { data: Slice[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const contained = data.find((d) => d.name === "Contained by bot")?.value ?? 0;
  const containment = total ? (contained / total) * 100 : 0;
  const slices = data.map((s, i) => ({ ...s, color: resolveColor(s.color, i) }));

  return (
    <div className="flex h-full flex-col rounded-large border border-border bg-surface p-200">
      <div className="mb-100">
        <h3 className="text-sm font-semibold text-text">Bot vs Human handling</h3>
        <p className="text-xs text-text-subtle">How every call ended up being resolved</p>
      </div>
      <div className="flex min-h-0 flex-1 items-center gap-200">
        <div className="relative h-40 w-40 shrink-0">
          <ResponsiveContainer>
            <PieChart>
              <Tooltip
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v: number, n) => [`${v.toLocaleString()} calls`, n as string]}
              />
              <Pie data={slices} innerRadius={44} outerRadius={70} paddingAngle={2} dataKey="value" stroke="none">
                {slices.map((s) => (
                  <Cell key={s.name} fill={s.color} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <div className="text-xl font-semibold text-text tabular">{containment.toFixed(0)}%</div>
            <div className="text-body-small text-text-subtle">Containment</div>
          </div>
        </div>
        <ul className="flex-1 space-y-100">
          {slices.map((s) => {
            const pct = total ? ((s.value / total) * 100).toFixed(1) : "0";
            return (
              <li key={s.name} className="flex items-center justify-between gap-100 text-xs">
                <span className="flex items-center gap-100">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
                  <span className="text-text">{s.name}</span>
                </span>
                <span className="tabular text-text-subtle">
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
