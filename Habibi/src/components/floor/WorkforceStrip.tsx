import { cn } from "@/lib/utils";
import type { FloorAgent } from "@/data/floor-seed";

const statusLabel: Record<FloorAgent["status"], string> = {
  on_call: "On call",
  available: "Free",
  wrap_up: "Wrap-up",
  on_break: "Break",
  offline: "Offline",
};

const statusDot: Record<FloorAgent["status"], string> = {
  on_call: "bg-background-brand-bold",
  available: "bg-background-success",
  wrap_up: "bg-background-warning",
  on_break: "bg-text-subtlest",
  offline: "bg-border-bold",
};

export function WorkforceStrip({
  agents,
  onSelect,
}: {
  agents: FloorAgent[];
  onSelect: (interactionId: string | null | undefined) => void;
}) {
  if (!agents.length) return null;
  const counts = agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.status] = (acc[a.status] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <div className="shrink-0 border-b border-border bg-surface px-200 py-100">
      <div className="mb-075 flex flex-wrap items-center gap-150 text-body-small text-text-subtlest">
        <span className="font-semibold text-text-subtle">Floor</span>
        {(Object.keys(statusLabel) as FloorAgent["status"][]).map((s) =>
          counts[s] ? (
            <span key={s} className="inline-flex items-center gap-050">
              <span className={cn("h-1.5 w-1.5 rounded-full", statusDot[s])} />
              {counts[s]} {statusLabel[s].toLowerCase()}
            </span>
          ) : null,
        )}
      </div>
      <div className="flex gap-075 overflow-x-auto pb-025">
        {agents.map((a) => (
          <button
            key={a.userId}
            type="button"
            onClick={() => onSelect(a.interactionId)}
            title={a.customer ? `${a.name} · ${a.customer}` : a.name}
            className="flex shrink-0 items-center gap-075 rounded-medium border border-border bg-surface px-100 py-050 hover:bg-surface-sunken"
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", statusDot[a.status])} />
            <span className="text-body-small font-semibold text-text">{a.initials}</span>
            <span className="max-w-[7rem] truncate text-body-small text-text-subtle">{a.name}</span>
            {a.customer && (
              <span className="hidden max-w-[8rem] truncate text-body-small text-text-subtlest sm:inline">
                {a.customer}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
