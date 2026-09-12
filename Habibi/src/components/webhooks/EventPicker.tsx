import { Checkbox } from "@/components/ui/checkbox";
import type { EventDef, EventKey } from "@/api/types/webhooks";
import { eventCategories } from "@/lib/webhooks";
import { cn, toggleIn } from "@/lib/utils";

/** The catalogue grouped by category, each event a checkbox; the sheet and the drawer both pick from it. */
export function EventPicker({
  catalog,
  selected,
  onChange,
  columns = 1,
}: {
  catalog: EventDef[];
  selected: EventKey[];
  onChange: (events: EventKey[]) => void;
  columns?: 1 | 2;
}) {
  return (
    <div className="space-y-150">
      {eventCategories(catalog).map((cat) => {
        const items = catalog.filter((e) => e.category === cat);
        const keys = items.map((e) => e.key);
        const allIn = keys.every((k) => selected.includes(k));
        return (
          <div key={cat} className="rounded-medium border border-border p-150">
            <div className="mb-100 flex items-center justify-between">
              <div className="text-body-small font-semibold text-text">{cat}</div>
              <button
                type="button"
                className="text-body-small text-text-brand hover:underline"
                onClick={() =>
                  onChange(
                    allIn
                      ? selected.filter((k) => !keys.includes(k))
                      : Array.from(new Set([...selected, ...keys])),
                  )
                }
              >
                {allIn ? "Clear group" : "Select all"}
              </button>
            </div>
            <div className={cn("grid gap-075", columns === 2 ? "grid-cols-2" : "grid-cols-1")}>
              {items.map((e) => (
                <label
                  key={e.key}
                  className="flex items-start gap-100 rounded p-075 text-body-small hover:bg-surface-sunken"
                >
                  <Checkbox
                    checked={selected.includes(e.key)}
                    onCheckedChange={() => onChange(toggleIn(selected, e.key))}
                    className="mt-025"
                  />
                  <span>
                    <span className="block font-mono text-body-small text-text-brand">{e.key}</span>
                    <span className="block text-body-small text-text-subtle">{e.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
