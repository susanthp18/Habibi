import type { AllowedWindow } from "@/data/consent-seed";

const DAYS = [
  { d: 1, label: "M" },
  { d: 2, label: "T" },
  { d: 3, label: "W" },
  { d: 4, label: "T" },
  { d: 5, label: "F" },
  { d: 6, label: "S" },
  { d: 0, label: "S" },
];

export function AllowedHoursEditor({
  window,
  timezone,
  onChange,
}: {
  window: AllowedWindow;
  timezone: string;
  onChange: (w: AllowedWindow) => void;
}) {
  const toggle = (d: number) => {
    const set = new Set(window.days);
    set.has(d) ? set.delete(d) : set.add(d);
    onChange({ ...window, days: Array.from(set).sort() });
  };

  return (
    <div className="space-y-2 rounded-md border border-[var(--border-token)] bg-surface-card p-3">
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wider text-text-muted">Allowed days</div>
        <div className="flex gap-1">
          {DAYS.map((d) => {
            const on = window.days.includes(d.d);
            return (
              <button
                key={d.d}
                onClick={() => toggle(d.d)}
                className={`h-7 w-7 rounded-md border text-[11px] font-semibold transition-colors ${
                  on
                    ? "border-brand-primary bg-brand-primary text-white"
                    : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken"
                }`}
              >
                {d.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-text-muted">Start</div>
          <select
            value={window.startHour}
            onChange={(e) => onChange({ ...window, startHour: Number(e.target.value) })}
            className="h-7 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
          >
            {Array.from({ length: 24 }, (_, i) => (
              <option key={i} value={i}>{String(i).padStart(2, "0")}:00</option>
            ))}
          </select>
        </div>
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-text-muted">End</div>
          <select
            value={window.endHour}
            onChange={(e) => onChange({ ...window, endHour: Number(e.target.value) })}
            className="h-7 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
          >
            {Array.from({ length: 24 }, (_, i) => (
              <option key={i} value={i}>{String(i).padStart(2, "0")}:00</option>
            ))}
          </select>
        </div>
        <div className="text-[11px] text-text-muted">Timezone: {timezone}</div>
      </div>
    </div>
  );
}
