import { ChartCard, ModernDonut, SnapshotPill } from "@/components/charts";

type Slice = { name: string; value: number; color: string };

const COLOR_ALIASES: Record<string, string> = {
  "var(--brand-primary)": "#1868db",
  "var(--brand-navy)": "#505258",
  "var(--success)": "#5b7f24",
  "var(--warning)": "#e06c00",
  "var(--chart-brand)": "#1868db",
  "var(--chart-success)": "#5b7f24",
  "var(--chart-warning)": "#e06c00",
  "var(--background-brand-bold)": "#1868db",
  "var(--background-brand-boldest)": "#505258",
  "var(--chart-success-bold)": "#5b7f24",
  "var(--chart-warning-bold)": "#e06c00",
  "var(--chart-gray-bold)": "#505258",
};

const FALLBACKS = ["#1868db", "#e06c00", "#505258"];

function resolveColor(color: string, index: number) {
  if (COLOR_ALIASES[color]) return COLOR_ALIASES[color];
  if (color.startsWith("#")) return color;
  return FALLBACKS[index % FALLBACKS.length];
}

export function BotVsHumanDonut({ data }: { data: Slice[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const contained = data.find((d) => d.name === "Contained by bot")?.value ?? 0;
  const containment = total ? (contained / total) * 100 : 0;
  const slices = data.map((s, i) => ({ ...s, color: resolveColor(s.color, i) }));

  return (
    <ChartCard
      title="Bot vs Human handling"
      subtitle="How every call ended up being resolved"
      action={<SnapshotPill />}
    >
      <div className="flex min-h-0 flex-1 items-center gap-200">
        <ModernDonut
          data={slices}
          centerValue={`${containment.toFixed(0)}%`}
          centerLabel="Containment"
          size={160}
          thickness={16}
        />
        <ul className="flex-1 space-y-100">
          {slices.map((s) => {
            const pct = total ? ((s.value / total) * 100).toFixed(1) : "0";
            return (
              <li
                key={s.name}
                className="flex items-center justify-between gap-100 text-body-small"
              >
                <span className="flex items-center gap-075">
                  <span className="size-2 rounded-full" style={{ background: s.color }} />
                  <span className="text-text">{s.name}</span>
                </span>
                <span className="tabular-nums text-text-subtlest">
                  {s.value.toLocaleString()} · {pct}%
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </ChartCard>
  );
}
