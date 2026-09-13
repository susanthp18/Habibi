import { ChartCard, ModernDonut, SnapshotPill } from "@/components/charts";

type Slice = { name: string; value: number; color: string };

// The API names its slice colours as tokens (`var(--background-brand-bold)`),
// and the donut is a CSS gradient, so they resolve in the theme they are
// drawn in. A map of token -> light-mode hex used to sit here and painted the
// light palette in dark mode. Anything that is not a token or a hex literal
// falls back to the categorical ramp.
const FALLBACKS = [
  "var(--chart-categorical-1)",
  "var(--chart-categorical-4)",
  "var(--chart-neutral)",
];

function resolveColor(color: string, index: number) {
  if (color.startsWith("var(--") || color.startsWith("#")) return color;
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
