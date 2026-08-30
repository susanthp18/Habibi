import { useRef } from "react";

import { cn } from "@/lib/utils";

/**
 * A number field you can drag, arrow, or type into.
 *
 * Voice tuning values (rate, pitch, style degree) are the kind of parameter you
 * adjust by feel and then need to pin exactly. A slider gives you the feel and
 * loses the precision; a text input gives you precision and no feel. This gives
 * both: drag the label to scrub, ⇧-arrow for coarse steps, or type the number.
 *
 * `active` renders the "changed from default" state, so a tuning panel shows at
 * a glance which knobs were actually touched — the question an operator asks
 * when a call sounds wrong is "what did I change?", not "what are the values?".
 */
export function ScrubField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  precision = 0,
  suffix,
  active,
  disabled,
  className,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  /** Decimal places to keep. Rate/pitch need 2; integers need 0. */
  precision?: number;
  suffix?: string;
  active?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const drag = useRef<{ x: number; v: number } | null>(null);

  const clamp = (v: number) => {
    const bounded = Math.min(max, Math.max(min, v));
    const factor = 10 ** precision;
    return Math.round(bounded * factor) / factor;
  };

  return (
    <label
      className={cn(
        "flex h-7 min-w-0 items-center gap-1 rounded-md py-1 pr-1 pl-0.5",
        "transition-[background-color,box-shadow] duration-200",
        disabled && "opacity-50",
        className,
      )}
      style={{
        background: active ? "var(--background-brand-subtlest)" : "var(--surface-sunken)",
        boxShadow: active ? "inset 0 0 0 1px var(--border-brand)" : "none",
      }}
    >
      <span
        role="slider"
        aria-label={label}
        aria-valuenow={value}
        // Omitted rather than announced as "Infinity". A param schema that
        // declares no bound is unbounded, and aria-valuemin="Infinity" is a
        // worse answer for a screen reader than no answer at all.
        aria-valuemin={Number.isFinite(min) ? min : undefined}
        aria-valuemax={Number.isFinite(max) ? max : undefined}
        aria-disabled={disabled}
        tabIndex={disabled ? -1 : 0}
        onPointerDown={(e) => {
          if (disabled) return;
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, v: value };
        }}
        onPointerMove={(e) => {
          if (!drag.current || disabled) return;
          // /2 keeps a full-width drag from blowing through the whole range —
          // these are fine adjustments, not a scrubber over a timeline.
          onChange(clamp(drag.current.v + ((e.clientX - drag.current.x) / 2) * step));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onKeyDown={(e) => {
          if (disabled) return;
          const mult = e.shiftKey ? 10 : 1;
          if (e.key === "ArrowUp" || e.key === "ArrowRight") {
            e.preventDefault();
            onChange(clamp(value + step * mult));
          } else if (e.key === "ArrowDown" || e.key === "ArrowLeft") {
            e.preventDefault();
            onChange(clamp(value - step * mult));
          }
        }}
        title={label}
        className={cn(
          // Was `shrink-0`, so a long label ("REPETITION PENALTY") could not
          // give way and instead pushed the value input out of the field and
          // clipped itself mid-word. It may shrink now, down to a floor that
          // still reads, and ellipsizes past that — the `title` keeps the full
          // name reachable, and the panel's container query means narrow is
          // rare rather than normal.
          "flex h-full min-w-0 max-w-[60%] shrink touch-none select-none items-center truncate rounded px-1",
          "text-body-tiny font-medium tracking-wide text-text-subtlest uppercase",
          !disabled && "cursor-ew-resize hover:text-text-subtle",
          "focus-visible:text-text-brand focus-visible:outline-none",
        )}
      >
        {label}
      </span>
      <input
        inputMode="decimal"
        disabled={disabled}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value.replace(/[^\d.-]/g, ""));
          if (!Number.isNaN(n)) onChange(clamp(n));
        }}
        aria-label={`${label} value`}
        className="min-w-0 flex-1 bg-transparent text-body-small text-text tabular-nums outline-none"
      />
      {suffix ? (
        <span className="shrink-0 pr-0.5 text-body-tiny text-text-subtlest">{suffix}</span>
      ) : null}
    </label>
  );
}

/**
 * Segmented control. The thumb slides rather than snapping so the eye tracks
 * which option it came from — cheap, and it is the difference between reading
 * as a control and reading as a set of buttons.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: { value: T; label: string; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  className?: string;
}) {
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn("relative grid rounded-md bg-surface-sunken p-0.5", className)}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden
        className="absolute inset-y-0.5 rounded bg-surface shadow-raised transition-transform duration-300"
        style={{
          width: `calc((100% - 4px) / ${options.length})`,
          left: 2,
          transform: `translateX(${index * 100}%)`,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          title={o.title}
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            // `truncate` was on this element while it was also `display:flex`,
            // where `text-overflow` has nothing to apply to — so a label wider
            // than its share did not ellipsize, it escaped the control and drew
            // over the neighbouring cell. The clipping now happens on the span.
            "relative z-10 flex h-6 min-w-0 items-center justify-center px-1.5",
            "text-body-small font-medium transition-colors duration-200",
            o.value === value ? "text-text-brand" : "text-text-subtlest hover:text-text-subtle",
          )}
        >
          <span className="min-w-0 truncate">{o.label}</span>
        </button>
      ))}
    </div>
  );
}
