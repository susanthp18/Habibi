import { cn } from "@/lib/utils";
import type { IntentAgg } from "@/data/bot-analytics-seed";
import { ChartCard, SnapshotPill } from "@/components/charts";

export function IntentDistribution({
  intents,
  activeId,
  onSelect,
}: {
  intents: IntentAgg[];
  activeId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const max = Math.max(...intents.map((i) => i.sessions), 1);
  return (
    <ChartCard
      title="Intent distribution"
      subtitle="Bar length = volume · color = containment"
      action={
        activeId ? (
          <button onClick={() => onSelect(null)} className="text-body-small text-text-brand hover:underline">
            Clear filter
          </button>
        ) : (
          <SnapshotPill />
        )
      }
    >
      <div className="-mx-050 space-y-050">
        {intents.map((it) => {
          const rate = (it.contained / (it.sessions || 1)) * 100;
          const active = activeId === it.id;
          const dim = activeId && !active;
          const barColor =
            rate >= 85
              ? "bg-background-success-bold"
              : rate >= 65
                ? "bg-background-warning-bold"
                : "bg-background-danger-bold";
          return (
            <button
              key={it.id}
              onClick={() => onSelect(active ? null : it.id)}
              className={cn(
                "grid w-full grid-cols-[9rem_1fr_6.5rem] items-center gap-150 rounded-medium px-100 py-075 text-left transition-colors hover:bg-surface-sunken",
                active && "bg-background-brand-subtlest hover:bg-background-brand-subtlest",
                dim && "opacity-50",
              )}
            >
              <div className="truncate text-[0.75rem] font-medium text-text">{it.label}</div>
              <div className="relative h-2.5 overflow-hidden rounded-full bg-surface-sunken p-0.5">
                <div
                  className={cn("h-full rounded-full transition-[width] duration-300", barColor)}
                  style={{ width: `${(it.sessions / max) * 100}%` }}
                />
              </div>
              <div className="text-right text-body-small text-text-subtle">
                <span className="mr-050 tabular-nums text-text-subtlest">{it.sessions.toLocaleString()}</span>
                <span
                  className={cn(
                    "font-semibold tabular-nums",
                    rate >= 85
                      ? "text-text-success-bolder"
                      : rate >= 65
                        ? "text-text-warning-bolder"
                        : "text-text-danger-bolder",
                  )}
                >
                  {rate.toFixed(0)}%
                </span>
              </div>
            </button>
          );
        })}
        {!intents.length && <div className="px-100 py-200 text-body-small text-text-subtlest">No intents in range.</div>}
      </div>
    </ChartCard>
  );
}
