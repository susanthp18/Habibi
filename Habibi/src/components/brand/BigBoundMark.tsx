import { useId } from "react";
import { cn } from "@/lib/utils";

type Props = {
  className?: string;
  size?: number;
  /** When false, skip CSS motion classes (mark stays static). */
  animated?: boolean;
};

/**
 * BigBound AI mark — circular 3D dialer (softphone faceplate).
 * No boxy tile: disc chassis + rotary holes + live hub pulse.
 */
export function BigBoundMark({ className, size = 32, animated = true }: Props) {
  const uid = useId().replace(/:/g, "");
  const g = (name: string) => `${uid}-${name}`;

  const holes = Array.from({ length: 8 }, (_, i) => {
    const a = ((i * 45 - 90) * Math.PI) / 180;
    return {
      key: i,
      cx: 20 + Math.cos(a) * 9.15,
      cy: 19.2 + Math.sin(a) * 9.15,
    };
  });

  const ticks = Array.from({ length: 16 }, (_, i) => {
    if (i % 2 === 0) return null;
    const a = ((i * 22.5 - 90) * Math.PI) / 180;
    return {
      key: `t${i}`,
      x1: 20 + Math.cos(a) * 11.35,
      y1: 19.2 + Math.sin(a) * 11.35,
      x2: 20 + Math.cos(a) * 12.6,
      y2: 19.2 + Math.sin(a) * 12.6,
    };
  }).filter(Boolean) as { key: string; x1: number; y1: number; x2: number; y2: number }[];

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("bb-dialer shrink-0", animated && "bb-dialer--live", className)}
      role="img"
      aria-label="BigBound AI"
    >
      <defs>
        <radialGradient id={g("face")} cx="36%" cy="30%" r="72%" fx="30%" fy="26%">
          <stop offset="0%" stopColor="#4BA3FF" />
          <stop offset="42%" stopColor="#1877F2" />
          <stop offset="100%" stopColor="#0B2447" />
        </radialGradient>
        <linearGradient id={g("rim")} x1="5" y1="3" x2="35" y2="37" gradientUnits="userSpaceOnUse">
          <stop stopColor="#9FD0FF" />
          <stop offset="0.28" stopColor="#1877F2" />
          <stop offset="0.7" stopColor="#0A4DA6" />
          <stop offset="1" stopColor="#061628" />
        </linearGradient>
        <linearGradient id={g("hub")} x1="14" y1="12" x2="27" y2="28" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FFFFFF" />
          <stop offset="0.5" stopColor="#DCEBFF" />
          <stop offset="1" stopColor="#7EAEF0" />
        </linearGradient>
        <radialGradient id={g("glow")} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#8FCBFF" stopOpacity="0.95" />
          <stop offset="70%" stopColor="#1877F2" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#1877F2" stopOpacity="0" />
        </radialGradient>
        <filter id={g("lift")} x="-35%" y="-35%" width="170%" height="170%">
          <feDropShadow dx="0" dy="1.4" stdDeviation="1.2" floodColor="#061628" floodOpacity="0.42" />
        </filter>
        <filter id={g("hubLift")} x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="0.9" stdDeviation="0.75" floodColor="#061628" floodOpacity="0.4" />
        </filter>
      </defs>

      {/* Soft ground contact */}
      <ellipse cx="20" cy="36.4" rx="11.5" ry="2.15" fill="#0B2447" opacity="0.16" />

      {/* Beveled chassis */}
      <circle cx="20" cy="19.2" r="16.5" fill={`url(#${g("rim")})`} filter={`url(#${g("lift")})`} />

      {/* Recessed faceplate */}
      <circle cx="20" cy="19.2" r="13.55" fill={`url(#${g("face")})`} />
      <circle cx="20" cy="19.2" r="13.55" stroke="#061628" strokeOpacity="0.25" strokeWidth="0.75" />

      {/* Top specular edge */}
      <path
        d="M7.9 13.8a13 13 0 0 1 24.2 0"
        stroke="white"
        strokeOpacity="0.32"
        strokeWidth="1.5"
        strokeLinecap="round"
      />

      {/* Dial ring — rotates when live */}
      <g className="bb-dialer__ring">
        {holes.map((h) => (
          <circle
            key={h.key}
            cx={h.cx}
            cy={h.cy}
            r="1.6"
            fill="#04101F"
            fillOpacity="0.42"
            stroke="white"
            strokeOpacity="0.2"
            strokeWidth="0.55"
          />
        ))}
        {ticks.map((t) => (
          <line
            key={t.key}
            x1={t.x1}
            y1={t.y1}
            x2={t.x2}
            y2={t.y2}
            stroke="white"
            strokeOpacity="0.38"
            strokeWidth="0.95"
            strokeLinecap="round"
          />
        ))}
      </g>

      {/* Live aura under hub */}
      <circle className="bb-dialer__pulse" cx="20" cy="19.2" r="6.4" fill={`url(#${g("glow")})`} />

      {/* Raised center hub + handset cue */}
      <g filter={`url(#${g("hubLift")})`}>
        <circle cx="20" cy="19.2" r="4.4" fill={`url(#${g("hub")})`} />
        <circle cx="20" cy="19.2" r="4.4" stroke="white" strokeOpacity="0.6" strokeWidth="0.75" />
        <path
          d="M17.7 17.95c.65-.85 1.4-1.2 2.2-1 .7.12 1.2.55 1.5 1.15"
          stroke="#0A4DA6"
          strokeWidth="1.2"
          strokeLinecap="round"
          fill="none"
        />
        <path
          d="M22.3 20.45c-.65.85-1.4 1.2-2.2 1-.7-.12-1.2-.55-1.5-1.15"
          stroke="#0A4DA6"
          strokeWidth="1.2"
          strokeLinecap="round"
          fill="none"
        />
        <circle cx="20" cy="19.2" r="1.1" fill="#1877F2" />
        <circle cx="19.35" cy="17.85" r="0.55" fill="white" fillOpacity="0.7" />
      </g>
    </svg>
  );
}
