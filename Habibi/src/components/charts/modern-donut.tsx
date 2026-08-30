"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";

export type DonutSlice = {
  name: string;
  value: number;
  color: string;
};

export function ModernDonut({
  data,
  centerValue,
  centerLabel,
  formatValue = (v) => v.toLocaleString(),
  size = 160,
  thickness = 18,
  className,
}: {
  data: DonutSlice[];
  centerValue?: string;
  centerLabel?: string;
  formatValue?: (v: number) => string;
  size?: number;
  thickness?: number;
  className?: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const total = data.reduce((s, d) => s + d.value, 0);

  const gradient = useMemo(() => {
    if (!total) return "var(--border)";
    let cursor = 0;
    const parts: string[] = [];
    for (const slice of data) {
      const start = cursor;
      const end = cursor + (slice.value / total) * 100;
      const dimmed = active && active !== slice.name;
      const color = dimmed ? `color-mix(in srgb, ${slice.color} 45%, transparent)` : slice.color;
      parts.push(`${color} ${start}% ${end}%`);
      cursor = end;
    }
    return `conic-gradient(${parts.join(", ")})`;
  }, [data, total, active]);

  const selected = data.find((d) => d.name === active);

  return (
    <div className={cn("relative shrink-0", className)} style={{ width: size, height: size }}>
      <div
        className="absolute inset-0 rounded-full transition-[background] duration-300"
        style={{ background: gradient }}
        role="img"
        aria-label="Distribution chart"
      />
      <div
        className="absolute inset-0 m-auto rounded-full bg-surface"
        style={{ width: size - thickness * 2, height: size - thickness * 2 }}
      />
      {/* hit targets */}
      <svg className="absolute inset-0" viewBox="0 0 100 100" aria-hidden>
        {(() => {
          let angle = -90;
          return data.map((slice) => {
            const sweep = total ? (slice.value / total) * 360 : 0;
            const start = angle;
            angle += sweep;
            const large = sweep > 180 ? 1 : 0;
            const r = 40;
            const toRad = (deg: number) => (deg * Math.PI) / 180;
            const x1 = 50 + r * Math.cos(toRad(start));
            const y1 = 50 + r * Math.sin(toRad(start));
            const x2 = 50 + r * Math.cos(toRad(start + sweep));
            const y2 = 50 + r * Math.sin(toRad(start + sweep));
            if (sweep <= 0) return null;
            return (
              <path
                key={slice.name}
                d={`M50,50 L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z`}
                fill="transparent"
                className="cursor-pointer"
                onPointerEnter={() => setActive(slice.name)}
                onPointerLeave={() => setActive(null)}
              />
            );
          });
        })()}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-3 text-center">
        <div className="heading-medium font-semibold tracking-tight text-text tabular-nums">
          {selected ? formatValue(selected.value) : centerValue}
        </div>
        <div className="text-body-micro text-text-subtlest">
          {selected ? selected.name : centerLabel}
        </div>
      </div>
    </div>
  );
}
