import { useId } from "react";
import { cn } from "@/lib/utils";

type Props = {
  className?: string;
  size?: number;
  /** When false, skip CSS motion classes (mark renders fully formed and static). */
  animated?: boolean;
};

/**
 * BigBound AI mark — architectural 'B' monogram over an ascending trend line.
 *
 * Two decisions worth keeping:
 *
 * 1. Both bowls close back onto the stem. An earlier draft let the lower bowl run off
 *    into the trajectory instead, which read as a 'P' with a hook at sidebar size.
 * 2. The trend line runs *under* the monogram, not beside it. Anything near-vertical
 *    placed to the right of a letterform gets read as a second letter — the versions
 *    with an ascending arc there read as "Bj" and "Bi".
 *
 * Palette is Design.md's brand family only (background-brand-boldest, background-brand-bold).
 * No cyan, no indigo, no glow filter: at 28px in the sidebar this sits next to the product
 * name, and it should not out-shout it.
 */

/** Monogram stem centre-line is x=9.9; both bowls start and end there so they merge. */
const BOWL_UPPER = "M9.9 7.3H19.6C23.6 7.3 26.6 9.6 26.6 12.5C26.6 15.4 23.6 17.7 19.6 17.7H9.9";
const BOWL_LOWER = "M9.9 17.7H20.6C24.9 17.7 28.2 19.7 28.2 22.2C28.2 24.7 24.9 26.7 20.6 26.7H9.9";
const TREND = "M6.8 35.2C15.4 34.4 26.2 32.6 34.2 27.2";

export function BigBoundMark({ className, size = 32, animated = true }: Props) {
  const uid = useId().replace(/:/g, "");
  // Two marks on one page collide on <defs> ids without this — the second renders unfilled.
  const g = (name: string) => `${uid}-${name}`;

  return (
    <span
      className={cn("bb-mark", animated && "bb-mark--live", className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label="BigBound AI"
    >
      <svg viewBox="0 0 40 40" width="100%" height="100%" aria-hidden="true">
        <defs>
          <linearGradient
            id={g("mono")}
            x1="8"
            y1="5"
            x2="29"
            y2="29"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#1C2B42" />
            <stop offset="1" stopColor="#1868DB" />
          </linearGradient>
        </defs>

        {/* Stem. Filled rather than stroked so the cap radius is exact. */}
        <rect x="7.6" y="5" width="4.6" height="24" rx="2.3" fill={`url(#${g("mono")})`} />

        {/* Bowls, stroked at the stem's own width so the monogram stays monoline. */}
        <path
          d={BOWL_UPPER}
          stroke={`url(#${g("mono")})`}
          strokeWidth="4.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
        <path
          d={BOWL_LOWER}
          stroke={`url(#${g("mono")})`}
          strokeWidth="4.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />

        {/* Trend line — lighter weight than the monogram so it reads as support, not a
            competing stroke. pathLength=100 keeps the draw-on independent of its length. */}
        <path
          className="bb-mark__trend"
          d={TREND}
          pathLength="100"
          stroke="#1868DB"
          strokeWidth="2.8"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
    </span>
  );
}
