import { cn } from "@/lib/utils";
import type { IntentAgg } from "@/data/bot-analytics-seed";

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
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div>
          <div className="text-body font-semibold text-text">Intent distribution</div>
          <div className="text-body-small text-text-subtlest">Bar length = volume · color = containment</div>
        </div>
        {activeId && (
          <button onClick={() => onSelect(null)} className="text-body-small text-text-brand hover:underline">
            Clear filter
          </button>
        )}
      </div>
      <div className="divide-y divide-border">
        {intents.map((it) => {
          const rate = (it.contained / (it.sessions || 1)) * 100;
          const active = activeId === it.id;
          const dim = activeId && !active;
          const barColor = rate >= 85 ? "bg-background-success-bold" : rate >= 65 ? "bg-background-warning-bold" : "bg-background-danger-bold";
          return (
            <button
              key={it.id}
              onClick={() => onSelect(active ? null : it.id)}
              className={cn(
                "grid w-full grid-cols-[160px_1fr_100px] items-center gap-150 px-150 py-100 text-left hover:bg-surface-sunken",
                active && "bg-background-brand-subtlest hover:bg-background-brand-subtlest",
                dim && "opacity-50",
              )}
            >
              <div className="truncate text-[0.75rem] font-medium text-text">{it.label}</div>
              <div className="relative h-4 rounded bg-surface-sunken">
                <div
                  className={cn("h-full rounded", barColor)}
                  style={{ width: `${(it.sessions / max) * 100}%` }}
                />
                <span className="absolute inset-0 flex items-center px-100 text-body-small font-medium text-white mix-blend-difference">
                  {it.sessions.toLocaleString()}
                </span>
              </div>
              <div className="text-right text-body-small text-text-subtle">
                <span className={cn("font-semibold", rate >= 85 ? "text-text-success-bolder" : rate >= 65 ? "text-text-warning-bolder" : "text-text-danger-bolder")}>
                  {rate.toFixed(0)}%
                </span>{" "}
                contained
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
