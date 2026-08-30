import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/* ─────────────────────────────────────────────────────────
 * LOADING STATE — pixel-grid loader for long-running work
 *
 * Variants:
 *   drive  — square cells, chevron wavefront driving right;
 *            the 650ms cycle is shorter than the sweep, so
 *            two fronts are always in flight
 *   dots   — same wavefront, circular cells
 *   orbit  — a comet lapping the grid perimeter
 *
 * Paired with a shimmering label and a live elapsed timer
 * in mono tabular figures. Reduced motion freezes the grid
 * to its dim state; the timer still ticks.
 * ───────────────────────────────────────────────────────── */

const chevron = Array.from({ length: 9 }, (_, i) => {
  const r = Math.floor(i / 3);
  const c = i % 3;
  return (c + Math.abs(r - 1)) * 90;
});

const ORBIT_ORDER = [0, 1, 2, 5, 8, 7, 6, 3];
const orbit = Array.from({ length: 9 }, (_, i) => {
  const k = ORBIT_ORDER.indexOf(i);
  return k === -1 ? null : k * 110;
});

type Variant = "drive" | "dots" | "orbit";

const PATTERNS: Record<Variant, { delays: (number | null)[]; dur: number; round: boolean }> = {
  drive: { delays: chevron, dur: 650, round: false },
  dots: { delays: chevron, dur: 650, round: true },
  orbit: { delays: orbit, dur: 950, round: false },
};

function useElapsed(active: boolean) {
  const [ds, setDs] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setDs((d) => d + 1), 100);
    return () => clearInterval(t);
  }, [active]);
  const total = ds / 10;
  if (total < 60) return `${total.toFixed(1)}s`;
  return `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return reduced;
}

export type LoadingStateProps = {
  label?: string;
  variant?: Variant;
  /** Center in a flex parent (typical full-page / panel fill). */
  center?: boolean;
  className?: string;
  /** Show the live elapsed timer (default true). */
  showTimer?: boolean;
};

export function LoadingState({
  label = "Loading",
  variant = "drive",
  center = false,
  className,
  showTimer = true,
}: LoadingStateProps) {
  const elapsed = useElapsed(showTimer);
  const reducedMotion = usePrefersReducedMotion();
  const { delays, dur, round } = PATTERNS[variant] ?? PATTERNS.drive;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={cn("flex w-fit items-center gap-150", center && "mx-auto", className)}
    >
      <span aria-hidden className="grid grid-cols-[repeat(3,4px)] gap-[1.5px]">
        {delays.map((d, i) => (
          <span
            key={i}
            className={cn("size-[4px] bg-text", round ? "rounded-full" : "rounded-[1px]")}
            style={{
              opacity: d === null ? 0.07 : 0.15,
              animation:
                d === null || reducedMotion
                  ? "none"
                  : `pixel-on ${dur}ms ease-in-out ${d}ms infinite`,
            }}
          />
        ))}
      </span>
      <span
        className={cn(
          "text-body-small font-medium",
          reducedMotion ? "text-text-subtlest" : "bg-clip-text text-transparent",
        )}
        style={
          reducedMotion
            ? undefined
            : {
                backgroundImage:
                  "linear-gradient(90deg, var(--text-subtlest) 35%, var(--text) 50%, var(--text-subtlest) 65%)",
                backgroundSize: "200% 100%",
                animation: "shimmer-text 1.4s linear infinite",
              }
        }
      >
        {label}
      </span>
      {showTimer && (
        <span className="font-mono text-body-small tabular-nums text-text-subtlest">{elapsed}</span>
      )}
    </div>
  );
}
