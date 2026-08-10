import { useRef } from "react";
import { sentimentColor, type SentimentPoint } from "@/data/audit-seed";

interface Props {
  points: SentimentPoint[];
  duration: number;
  currentTime: number;
  markers?: { t: number; tone: string; label: string }[];
  onSeek: (t: number) => void;
}

export function SentimentTimeline({ points, duration, currentTime, markers = [], onSeek }: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const w = 100;
  const h = 40;

  if (points.length < 2) return null;

  const path = points
    .map((p, i) => {
      const x = (p.t / duration) * w;
      const y = h / 2 - (p.v * h) / 2;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const avg = points.reduce((s, p) => s + p.v, 0) / points.length;
  const playX = (currentTime / duration) * w;

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const t = Math.max(0, Math.min(duration, (x / rect.width) * duration));
    onSeek(t);
  };

  return (
    <div>
      <div className="mb-050 flex items-center justify-between text-body-small text-text-subtlest">
        <span>Sentiment timeline</span>
        <span className="font-mono">avg {avg.toFixed(2)}</span>
      </div>
      <svg
        ref={ref}
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="h-800 w-full cursor-crosshair rounded-medium border border-border bg-surface-sunken"
        onClick={handleClick}
      >
        <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="var(--border)" strokeDasharray="1 1.5" strokeWidth={0.3} />
        <path d={path} fill="none" stroke={sentimentColor(avg)} strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
        {markers.map((m, i) => (
          <line
            key={i}
            x1={(m.t / duration) * w}
            x2={(m.t / duration) * w}
            y1={0}
            y2={h}
            stroke={m.tone}
            strokeWidth={0.6}
            vectorEffect="non-scaling-stroke"
            opacity={0.7}
          >
            <title>{m.label}</title>
          </line>
        ))}
        <line
          x1={playX}
          x2={playX}
          y1={0}
          y2={h}
          stroke="var(--background-brand-bold)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}
