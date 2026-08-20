"use client";

import { useId, useMemo, type CSSProperties } from "react";
import { buildSmoothPath } from "./points";
import { cn } from "@/lib/utils";

export function LivelineSpark({
  data,
  color = "#1868db",
  className,
  height = 32,
  style,
}: {
  data: number[];
  color?: string;
  className?: string;
  height?: number;
  style?: CSSProperties;
}) {
  const uid = useId().replace(/:/g, "");
  const width = 120;
  const path = useMemo(() => {
    const min = Math.min(0, ...data);
    const max = Math.max(...data, min + 1e-6);
    return buildSmoothPath(data, width, height, { top: 2, bottom: 2 }, min, max);
  }, [data, height]);

  if (!data.length) return null;

  return (
    <div className={cn("overflow-hidden", className)} style={{ height, width: "100%", ...style }}>
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden
        className="block"
      >
        <defs>
          <linearGradient id={`spark-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={path.area} fill={`url(#spark-${uid})`} />
        <path
          d={path.line}
          fill="none"
          stroke={color}
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}
