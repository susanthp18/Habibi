"use client";

import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  chartIndexFromPointer,
  buildSmoothPath,
  valueToY,
  DEFAULT_PADS,
  type PathPads,
} from "./points";
import { ChartTooltip } from "./chart-shell";
import { cn } from "@/lib/utils";

type SeriesInput = {
  id: string;
  label: string;
  values: number[];
  color: string;
};

type Props = {
  values?: number[];
  series?: SeriesInput[];
  color?: string;
  height?: number;
  formatValue?: (v: number) => string;
  formatTime?: (index: number) => string;
  labels?: string[];
  grid?: boolean;
  fill?: boolean;
  className?: string;
  /** Floor domain at 0 (cost / count charts). Default true for multi-series. */
  zeroBaseline?: boolean;
};

/**
 * Snapshot trend chart — scrubbable SVG area/line (and multi-series).
 * Shared y-domain + monotone cubics keep every series on the same glossy scale.
 */
export function LivelineTrend({
  values,
  series: seriesInput,
  color = "#1868db",
  height = 180,
  formatValue = (v) => String(Math.round(v)),
  formatTime,
  labels,
  grid = false,
  fill = true,
  className,
  zeroBaseline,
}: Props) {
  const uid = useId().replace(/:/g, "");
  const rootRef = useRef<HTMLDivElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [size, setSize] = useState({ w: 320, h: height });

  const multi = Boolean(seriesInput?.length);
  const pointCount = multi ? (seriesInput?.[0]?.values.length ?? 0) : (values?.length ?? 0);
  const floorZero = zeroBaseline ?? multi;
  const pads: PathPads = grid ? { top: 18, bottom: 16 } : DEFAULT_PADS;

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const update = () => {
      const w = Math.round(node.clientWidth);
      const h = Math.round(node.clientHeight || height);
      if (w <= 0 || h <= 0) return;
      setSize((prev) => (Math.abs(prev.w - w) > 1 || Math.abs(prev.h - h) > 1 ? { w, h } : prev));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, [height]);

  const domain = useMemo(() => {
    const all = multi ? (seriesInput ?? []).flatMap((s) => s.values) : (values ?? []);
    if (!all.length) return { min: 0, max: 1 };
    const dataMin = Math.min(...all);
    const dataMax = Math.max(...all);
    const min = floorZero ? Math.min(0, dataMin) : dataMin;
    const max = Math.max(dataMax, min + 1e-6);
    // Small headroom so peaks don't clip the stroke
    const pad = (max - min) * 0.06;
    return { min, max: max + pad };
  }, [multi, seriesInput, values, floorZero]);

  const paths = useMemo(() => {
    if (multi && seriesInput?.length) {
      return seriesInput.map((s) => ({
        ...s,
        ...buildSmoothPath(s.values, size.w, size.h, pads, domain.min, domain.max),
      }));
    }
    const built = buildSmoothPath(values ?? [], size.w, size.h, pads, domain.min, domain.max);
    return [{ id: "main", label: "Value", values: values ?? [], color, ...built }];
  }, [multi, seriesInput, values, color, size.w, size.h, pads, domain.min, domain.max]);

  if (pointCount === 0) return null;

  const onMove = (event: PointerEvent<HTMLDivElement>) => {
    setHoverIndex(chartIndexFromPointer(event, pointCount));
  };
  const clear = () => setHoverIndex(null);

  const tooltipRows =
    hoverIndex !== null
      ? paths.map((s) => ({
          label: s.label,
          value: formatValue(s.values[hoverIndex] ?? 0),
          color: s.color,
        }))
      : [];

  const timeLabel =
    hoverIndex !== null
      ? (formatTime?.(hoverIndex) ?? labels?.[hoverIndex] ?? undefined)
      : undefined;

  const cursorX =
    hoverIndex !== null && pointCount > 1 ? (hoverIndex / (pointCount - 1)) * 100 : 50;

  // Flip tooltip to the open side of the cursor so it never covers the active point
  const tooltipOnLeft = cursorX > 58;
  const tooltipStyle = tooltipOnLeft
    ? { left: `${cursorX}%`, transform: "translateX(calc(-100% - 12px))" }
    : { left: `${cursorX}%`, transform: "translateX(12px)" };

  return (
    <div
      ref={rootRef}
      className={cn("chart-stage relative h-full min-h-[10rem] w-full", className)}
      style={{ minHeight: height }}
      onPointerDown={onMove}
      onPointerMove={onMove}
      onPointerLeave={clear}
      onPointerCancel={clear}
      onPointerUp={clear}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${size.w} ${size.h}`}
        preserveAspectRatio="none"
        className="block"
      >
        <defs>
          {paths.map((s) => (
            <linearGradient key={s.id} id={`fill-${uid}-${s.id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={multi ? 0.28 : 0.38} />
              <stop offset="55%" stopColor={s.color} stopOpacity={multi ? 0.1 : 0.14} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>

        {grid
          ? [0.25, 0.5, 0.75].map((t) => {
              const y = pads.top + (1 - t) * (size.h - pads.top - pads.bottom);
              return (
                <line
                  key={t}
                  x1={0}
                  x2={size.w}
                  y1={y}
                  y2={y}
                  stroke="var(--border)"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              );
            })
          : null}

        {/* Draws fills first (back), then strokes on top for a consistent glossy stack */}
        {fill
          ? paths.map((s) => (
              <path key={`fill-${s.id}`} d={s.area} fill={`url(#fill-${uid}-${s.id})`} />
            ))
          : null}
        {paths.map((s) => (
          <path
            key={`line-${s.id}`}
            d={s.line}
            fill="none"
            stroke={s.color}
            strokeWidth={2.25}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {hoverIndex !== null && pointCount > 1
          ? paths.map((s) => {
              const v = s.values[hoverIndex] ?? 0;
              const x = (hoverIndex / (pointCount - 1)) * size.w;
              const y = valueToY(v, size.h, domain.min, domain.max, pads);
              return (
                <g key={`dot-${s.id}`}>
                  <circle cx={x} cy={y} r={6} fill={s.color} opacity={0.18} />
                  <circle
                    cx={x}
                    cy={y}
                    r={3.5}
                    fill={s.color}
                    stroke="var(--surface)"
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              );
            })
          : null}
      </svg>

      {hoverIndex !== null && pointCount > 1 ? (
        <>
          <span className="chart-cursor" style={{ left: `${cursorX}%` }} />
          <span className="chart-tooltip-anchor" style={tooltipStyle}>
            <ChartTooltip time={timeLabel} rows={tooltipRows} />
          </span>
        </>
      ) : null}
    </div>
  );
}
