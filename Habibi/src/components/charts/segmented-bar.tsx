"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

export type Segment = {
  id: string;
  label: string;
  pct: number;
  color: string;
  valueLabel?: string;
  detail?: string;
};

export function SegmentedBar({
  segments,
  title,
  className,
}: {
  segments: Segment[];
  title?: string;
  className?: string;
}) {
  const [selected, setSelected] = useState(
    () => [...segments].sort((a, b) => b.pct - a.pct)[0]?.id ?? segments[0]?.id ?? "",
  );
  const active = segments.find((s) => s.id === selected) ?? segments[0];

  if (!segments.length) return null;

  return (
    <div className={cn("flex h-full flex-col", className)}>
      {title ? <span className="text-body-small font-medium text-text">{title}</span> : null}
      {active?.valueLabel ? (
        <span className="mt-050 block heading-medium font-semibold tracking-tight text-text tabular-nums">
          {active.valueLabel}
        </span>
      ) : null}

      <div
        className="mt-150 flex h-9 overflow-hidden rounded-full bg-surface-sunken p-0.5"
        role="group"
        aria-label="Distribution segments"
      >
        {segments.map((s, i) => {
          const isFirst = i === 0;
          const isLast = i === segments.length - 1;
          return (
            <button
              key={s.id}
              type="button"
              aria-pressed={selected === s.id}
              aria-label={`${s.label}: ${s.pct.toFixed(1)}%`}
              onClick={() => setSelected(s.id)}
              className={cn(
                "relative h-full min-w-0 overflow-hidden transition-[opacity,transform,filter] duration-300 active:scale-[0.99]",
                isFirst && "rounded-l-full",
                isLast && "rounded-r-full",
              )}
              style={{
                flex: `${Math.max(s.pct, 0.5)} 1 0%`,
                background: s.color,
                opacity: selected === s.id ? 1 : 0.55,
                filter: selected === s.id ? "none" : "saturate(0.9)",
                transitionTimingFunction: EASE,
              }}
            >
              <span
                className="absolute inset-y-1 left-1 rounded-full bg-white/20 transition-[width,opacity] duration-500"
                style={{
                  width: selected === s.id ? "calc(100% - 8px)" : "0%",
                  opacity: selected === s.id ? 1 : 0,
                  transitionTimingFunction: EASE,
                }}
              />
            </button>
          );
        })}
      </div>

      <div className="mt-100 flex flex-wrap items-center gap-050">
        {segments.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-pressed={selected === s.id}
            onClick={() => setSelected(s.id)}
            className={cn(
              "flex items-center gap-050 rounded-full px-075 py-025 text-body-tiny transition-[background-color,color,transform] duration-150 active:scale-[0.96]",
              selected === s.id
                ? "bg-surface-sunken text-text"
                : "text-text-subtle hover:bg-surface-sunken hover:text-text",
            )}
          >
            <span className="size-1.5 rounded-full" style={{ background: s.color }} />
            {s.label} <span className="tabular-nums">{s.pct.toFixed(1)}%</span>
          </button>
        ))}
      </div>

      {active?.detail ? (
        <div className="mt-150 min-h-16 rounded-medium bg-surface-sunken px-150 py-100 shadow-raised">
          <span className="block text-body-small font-medium text-text">{active.label}</span>
          <span className="mt-050 block text-body-tiny leading-relaxed text-text-subtlest">
            {active.detail}
          </span>
        </div>
      ) : null}
    </div>
  );
}
