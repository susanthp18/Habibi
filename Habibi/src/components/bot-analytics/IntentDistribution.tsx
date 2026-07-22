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
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div>
          <div className="text-[13px] font-semibold text-brand-navy">Intent distribution</div>
          <div className="text-[11px] text-text-muted">Bar length = volume · color = containment</div>
        </div>
        {activeId && (
          <button onClick={() => onSelect(null)} className="text-[11px] text-brand-primary hover:underline">
            Clear filter
          </button>
        )}
      </div>
      <div className="divide-y divide-[var(--border-token)]">
        {intents.map((it) => {
          const rate = (it.contained / (it.sessions || 1)) * 100;
          const active = activeId === it.id;
          const dim = activeId && !active;
          const barColor = rate >= 85 ? "bg-emerald-500" : rate >= 65 ? "bg-amber-500" : "bg-red-500";
          return (
            <button
              key={it.id}
              onClick={() => onSelect(active ? null : it.id)}
              className={cn(
                "grid w-full grid-cols-[160px_1fr_100px] items-center gap-3 px-3 py-2 text-left hover:bg-surface-sunken",
                active && "bg-brand-tint hover:bg-brand-tint",
                dim && "opacity-50",
              )}
            >
              <div className="truncate text-[12.5px] font-medium text-brand-navy">{it.label}</div>
              <div className="relative h-4 rounded bg-surface-sunken">
                <div
                  className={cn("h-full rounded", barColor)}
                  style={{ width: `${(it.sessions / max) * 100}%` }}
                />
                <span className="absolute inset-0 flex items-center px-2 text-[11px] font-medium text-white mix-blend-difference">
                  {it.sessions.toLocaleString()}
                </span>
              </div>
              <div className="text-right text-[11px] text-text-secondary">
                <span className={cn("font-semibold", rate >= 85 ? "text-emerald-700" : rate >= 65 ? "text-amber-700" : "text-red-700")}>
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
