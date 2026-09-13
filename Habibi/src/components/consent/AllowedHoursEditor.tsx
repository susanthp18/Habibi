import { SelectField } from "@/components/ui/select";
import type { AllowedWindow } from "@/api/types/consent";

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => ({
  value: String(i),
  label: `${String(i).padStart(2, "0")}:00`,
}));

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
    if (set.has(d)) set.delete(d);
    else set.add(d);
    onChange({ ...window, days: Array.from(set).sort() });
  };

  return (
    <div className="space-y-100 rounded-medium border border-border bg-surface p-150">
      <div>
        <div className="mb-050 text-body-small text-text-subtlest">Allowed days</div>
        <div className="flex gap-050">
          {DAYS.map((d) => {
            const on = window.days.includes(d.d);
            return (
              <button
                key={d.d}
                onClick={() => toggle(d.d)}
                className={`h-7 w-7 rounded-medium border text-body-small font-semibold transition-colors ${
                  on
                    ? "border-border-brand bg-background-brand-bold text-text-inverse"
                    : "border-border bg-surface text-text-subtle hover:bg-surface-sunken"
                }`}
              >
                {d.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-150">
        <div>
          <div className="mb-050 text-body-small text-text-subtlest">Start</div>
          <SelectField
            aria-label="Start hour"
            value={String(window.startHour)}
            onChange={(v) => onChange({ ...window, startHour: Number(v) })}
            size="compact"
            className="w-[6.25rem]"
            options={HOUR_OPTIONS}
          />
        </div>
        <div>
          <div className="mb-050 text-body-small text-text-subtlest">End</div>
          <SelectField
            aria-label="End hour"
            value={String(window.endHour)}
            onChange={(v) => onChange({ ...window, endHour: Number(v) })}
            size="compact"
            className="w-[6.25rem]"
            options={HOUR_OPTIONS}
          />
        </div>
        <div className="text-body-small text-text-subtlest">Timezone: {timezone}</div>
      </div>
    </div>
  );
}
