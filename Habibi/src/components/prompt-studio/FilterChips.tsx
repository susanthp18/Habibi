import { cn } from "@/lib/utils";

export type FilterChip = {
  key: string;
  label: string;
  /** Provider dot, severity dot — omit for plain chips. */
  dot?: string;
  count: number;
  /** Rendered muted with a tooltip rather than hidden. See note below. */
  disabled?: boolean;
  title?: string;
};

/**
 * A horizontal chip row that filters the list beneath it.
 *
 * Counts are part of the control, not decoration: "Cartesia 24" tells you
 * whether clicking is worth it before you click. A chip whose count is zero
 * still renders — a provider that silently vanishes from the picker makes
 * "why can't I choose ElevenLabs?" unanswerable from the screen, which is the
 * exact question an operator asks when a key has not been configured.
 */
export function FilterChips({
  chips,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  chips: FilterChip[];
  value: string;
  onChange: (key: string) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn("-mx-1 flex items-center gap-1 overflow-x-auto px-1 py-1", className)}
      style={{ scrollbarWidth: "none" }}
    >
      {chips.map((chip) => {
        const active = value === chip.key;
        return (
          <button
            key={chip.key}
            type="button"
            aria-pressed={active}
            title={chip.title}
            onClick={() => onChange(chip.key)}
            className={cn(
              "flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-body-small font-medium",
              "transition-[background-color,box-shadow,color] duration-200",
              active
                ? "bg-surface text-text shadow-raised"
                : "text-text-subtle hover:bg-surface-hovered",
              chip.disabled && "opacity-55",
            )}
          >
            {chip.dot ? (
              <span className="size-1.5 shrink-0 rounded-full" style={{ background: chip.dot }} />
            ) : null}
            {chip.label}
            <span
              className={cn(
                "rounded px-1 text-body-micro tabular-nums",
                active ? "bg-surface-sunken text-text-subtle" : "text-text-subtlest",
              )}
            >
              {chip.count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
