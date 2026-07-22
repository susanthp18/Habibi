import type { OptOutEvent } from "@/data/consent-seed";

export function OptOutLog({ events }: { events: OptOutEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] bg-surface-card px-3 py-4 text-center text-[11px] text-text-muted">
        No opt-out events on record.
      </div>
    );
  }
  return (
    <ul className="space-y-1">
      {events.slice().reverse().map((e) => (
        <li key={e.id} className="rounded-md border border-[var(--border-token)] bg-surface-card p-2 text-[12px]">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-full bg-[color:var(--danger-bg)] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[color:var(--danger)]">
              {e.channel === "all" ? "All" : e.channel}
            </span>
            <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-text-secondary">
              {e.source}
            </span>
            <span className="ml-auto text-[10px] text-text-muted">
              {new Date(e.at).toLocaleString()} · {e.actor}
            </span>
          </div>
          <div className="mt-1 text-[12px] text-text-primary">{e.note}</div>
        </li>
      ))}
    </ul>
  );
}
