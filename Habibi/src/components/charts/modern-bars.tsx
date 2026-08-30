"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { ChartTooltip } from "./chart-shell";

export type BarDatum = {
  label: string;
  value: number;
  color?: string;
  stack?: { key: string; value: number; color: string; label: string }[];
};

export function ModernBars({
  data,
  height = 200,
  formatValue = (v) => v.toLocaleString(),
  className,
}: {
  data: BarDatum[];
  height?: number;
  formatValue?: (v: number) => string;
  className?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [plotH, setPlotH] = useState(Math.max(80, height - 22));
  const max = Math.max(...data.map((d) => d.value), 1);
  const labelH = 22;

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const update = () => {
      const h = Math.round(node.clientHeight);
      if (h > 0) setPlotH(Math.max(80, h - labelH));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={rootRef}
      className={cn("relative h-full w-full", className)}
      style={{ minHeight: height }}
    >
      <div className="relative flex items-end gap-1.5 px-1" style={{ height: plotH }}>
        {data.map((d, i) => {
          const barH = Math.max(d.value > 0 ? 6 : 0, (d.value / max) * plotH);
          const active = hover === i;
          return (
            <button
              key={`${d.label}-${i}`}
              type="button"
              className="group relative flex min-w-0 flex-1 flex-col justify-end"
              style={{ height: plotH }}
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              {d.stack?.length ? (
                <div
                  className={cn(
                    "flex w-full flex-col justify-end overflow-hidden rounded-t-[6px] transition-opacity duration-150",
                    active ? "opacity-100" : "opacity-85",
                  )}
                  style={{ height: barH }}
                >
                  {[...d.stack].reverse().map((seg) => {
                    const segH = d.value > 0 ? (seg.value / d.value) * barH : 0;
                    return (
                      <div
                        key={seg.key}
                        className="w-full"
                        style={{
                          height: Math.max(seg.value > 0 ? 2 : 0, segH),
                          background: seg.color,
                        }}
                      />
                    );
                  })}
                </div>
              ) : (
                <div
                  className={cn(
                    "w-full rounded-t-[6px] transition-[opacity,box-shadow] duration-150",
                    active ? "opacity-100 shadow-raised" : "opacity-85",
                  )}
                  style={{
                    height: barH,
                    background: d.color ?? "var(--background-brand-bold)",
                  }}
                />
              )}
            </button>
          );
        })}

        {hover !== null ? (
          <span
            className="chart-tooltip-anchor pointer-events-none absolute top-1 z-10"
            style={
              (hover + 0.5) / data.length > 0.58
                ? {
                    left: `${((hover + 0.5) / data.length) * 100}%`,
                    transform: "translateX(calc(-100% - 8px))",
                  }
                : {
                    left: `${((hover + 0.5) / data.length) * 100}%`,
                    transform: "translateX(8px)",
                  }
            }
          >
            <ChartTooltip
              time={data[hover].label}
              rows={
                data[hover].stack?.length
                  ? data[hover]
                      .stack!.filter((s) => s.value > 0)
                      .map((s) => ({
                        label: s.label,
                        value: formatValue(s.value),
                        color: s.color,
                      }))
                  : [
                      {
                        label: data[hover].label,
                        value: formatValue(data[hover].value),
                        color: data[hover].color ?? "var(--background-brand-bold)",
                      },
                    ]
              }
            />
          </span>
        ) : null}
      </div>

      <div className="mt-050 flex gap-1.5 px-1">
        {data.map((d, i) => (
          <div
            key={`${d.label}-lbl-${i}`}
            className={cn(
              "min-w-0 flex-1 truncate text-center text-body-micro tabular-nums text-text-subtlest",
              hover === i && "font-medium text-text",
            )}
          >
            {d.label}
          </div>
        ))}
      </div>
    </div>
  );
}
