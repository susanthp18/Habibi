import type { OptOutEvent } from "@/data/consent-seed";
import { Lozenge } from "@/components/ui/lozenge";

export function OptOutLog({ events }: { events: OptOutEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border bg-surface px-150 py-200 text-center text-body-small text-text-subtlest">
        No opt-out events on record.
      </div>
    );
  }
  return (
    <ul className="space-y-050">
      {events.slice().reverse().map((e) => (
        <li key={e.id} className="rounded-medium border border-border bg-surface p-100 text-body-small">
          <div className="flex flex-wrap items-center gap-075">
            <Lozenge tone="danger">
              {e.channel === "all" ? "All" : e.channel}
            </Lozenge>
            <Lozenge tone="neutral">
              {e.source}
            </Lozenge>
            <span className="ml-auto text-body-small text-text-subtlest">
              {new Date(e.at).toLocaleString()} · {e.actor}
            </span>
          </div>
          <div className="mt-050 text-body-small text-text">{e.note}</div>
        </li>
      ))}
    </ul>
  );
}
