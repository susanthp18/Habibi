import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

function readWidths(key: string, fallback: number[]): number[] | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as number[];
    if (!Array.isArray(parsed) || parsed.length !== fallback.length) return null;
    if (!parsed.every((n) => typeof n === "number" && Number.isFinite(n) && n > 0)) return null;
    const sum = parsed.reduce((a, b) => a + b, 0);
    if (Math.abs(sum - 100) > 2) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeWidths(key: string, widths: number[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(widths));
  } catch {
    /* ignore */
  }
}

/** Lightweight horizontal split — no react-resizable-panels (avoids layout throws). */
export function SplitPanes({
  storageKey,
  defaultWidths,
  minWidthsPx,
  children,
  className,
}: {
  storageKey: string;
  defaultWidths: number[];
  minWidthsPx: number[];
  children: ReactNode[];
  className?: string;
}) {
  const panes = children.filter((c) => c != null && c !== false) as ReactNode[];
  const count = panes.length;
  const defaults = defaultWidths.slice(0, count);
  while (defaults.length < count) defaults.push(100 / Math.max(count, 1));

  const [widths, setWidths] = useState<number[]>(() => defaults);
  const rootRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ index: number; startX: number; startWidths: number[] } | null>(null);

  useEffect(() => {
    const saved = readWidths(storageKey, defaults);
    setWidths(saved ?? defaults);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, count]);

  const onPointerDown = useCallback(
    (index: number, e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      dragRef.current = { index, startX: e.clientX, startWidths: [...widths] };
    },
    [widths],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      const root = rootRef.current;
      if (!drag || !root) return;
      const totalPx = root.getBoundingClientRect().width;
      if (totalPx <= 0) return;
      const deltaPct = ((e.clientX - drag.startX) / totalPx) * 100;
      const i = drag.index;
      const next = [...drag.startWidths];
      const leftMin = ((minWidthsPx[i] ?? 160) / totalPx) * 100;
      const rightMin = ((minWidthsPx[i + 1] ?? 160) / totalPx) * 100;
      const pair = next[i] + next[i + 1];
      const lo = leftMin;
      const hi = pair - rightMin;
      const left =
        lo <= hi
          ? clamp(next[i] + deltaPct, lo, hi)
          : Math.max(0, Math.min(pair, (pair * leftMin) / (leftMin + rightMin || 1)));
      next[i] = left;
      next[i + 1] = pair - left;
      setWidths(next);
    },
    [minWidthsPx],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      dragRef.current = null;
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      setWidths((w) => {
        writeWidths(storageKey, w);
        return w;
      });
    },
    [storageKey],
  );

  // Keyboard resize for the focusable separator (a11y parity with pointer drag).
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>, i: number) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const root = rootRef.current;
      if (!root) return;
      e.preventDefault();
      const totalPx = root.getBoundingClientRect().width;
      if (totalPx <= 0) return;
      const stepPx = e.key === "ArrowLeft" ? -10 : 10;
      const deltaPct = (stepPx / totalPx) * 100;
      const next = [...widths];
      const leftMin = ((minWidthsPx[i] ?? 160) / totalPx) * 100;
      const rightMin = ((minWidthsPx[i + 1] ?? 160) / totalPx) * 100;
      const pair = next[i] + next[i + 1];
      const lo = leftMin;
      const hi = pair - rightMin;
      const left =
        lo <= hi
          ? clamp(next[i] + deltaPct, lo, hi)
          : Math.max(0, Math.min(pair, (pair * leftMin) / (leftMin + rightMin || 1)));
      next[i] = left;
      next[i + 1] = pair - left;
      setWidths(next);
      writeWidths(storageKey, next);
    },
    [widths, minWidthsPx, storageKey],
  );

  return (
    <div ref={rootRef} className={cn("flex h-full min-h-0 w-full overflow-hidden", className)}>
      {panes.map((child, i) => (
        <Fragment key={i}>
          <div
            className="min-h-0 min-w-0 overflow-hidden"
            style={{ flexBasis: `${widths[i] ?? defaults[i]}%`, flexGrow: 0, flexShrink: 0 }}
          >
            {child}
          </div>
          {i < panes.length - 1 && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize panels"
              aria-valuemin={Math.round(minWidthsPx[i] ?? 160)}
              aria-valuemax={100 - Math.round(minWidthsPx[i + 1] ?? 160)}
              aria-valuenow={Math.round(widths[i])}
              tabIndex={0}
              onPointerDown={(e) => onPointerDown(i, e)}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onKeyDown={(e) => onKeyDown(e, i)}
              className="focus-ring group relative z-10 flex w-1.5 shrink-0 cursor-col-resize items-center justify-center bg-border hover:bg-background-brand-bold/35 active:bg-background-brand-bold/50"
            >
              <div className="pointer-events-none h-400 w-050 rounded-full bg-text-muted/40 opacity-0 transition-opacity group-hover:opacity-100" />
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}
