import { useMemo } from "react";
import { TrendingDown, TrendingUp, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  /** -1..+1 samples, oldest → newest */
  series: number[];
};

export function SentimentMeter({ series }: Props) {
  const current = series[series.length - 1] ?? 0;
  const prev = series[series.length - 6] ?? current;
  const delta = current - prev;

  const label =
    current > 0.25 ? "Positive" : current < -0.2 ? "Negative" : "Neutral";
  const color =
    current > 0.25
      ? "var(--sentiment-positive)"
      : current < -0.2
        ? "var(--sentiment-negative)"
        : "var(--sentiment-neutral)";

  const trend =
    Math.abs(delta) < 0.05 ? "flat" : delta > 0 ? "up" : "down";

  const path = useMemo(() => buildPath(series, 260, 44), [series]);
  const gaugePct = ((current + 1) / 2) * 100;

  return (
    <section className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex items-center gap-6">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Live sentiment
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-[20px] font-semibold" style={{ color }}>
              {label}
            </span>
            <span className="tabular text-[12px] text-text-secondary">
              {current >= 0 ? "+" : ""}
              {current.toFixed(2)}
            </span>
            <span
              className={cn(
                "flex items-center gap-0.5 text-[11px] font-medium",
                trend === "up" && "text-success",
                trend === "down" && "text-danger",
                trend === "flat" && "text-text-muted",
              )}
            >
              {trend === "up" && <TrendingUp className="h-3 w-3" />}
              {trend === "down" && <TrendingDown className="h-3 w-3" />}
              {trend === "flat" && <Minus className="h-3 w-3" />}
              {trend !== "flat" && `${(delta * 100).toFixed(0)}%`}
              {trend === "flat" && "stable"}
            </span>
          </div>
        </div>

        {/* Gauge bar */}
        <div className="min-w-[160px] flex-1">
          <div className="relative h-2 w-full overflow-hidden rounded-full"
               style={{ background: "linear-gradient(90deg, var(--sentiment-negative) 0%, var(--sentiment-neutral) 50%, var(--sentiment-positive) 100%)" }}>
            <div
              className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-md"
              style={{ left: `${gaugePct}%`, background: color }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-text-muted">
            <span>Negative</span>
            <span>Neutral</span>
            <span>Positive</span>
          </div>
        </div>

        {/* Sparkline */}
        <div className="hidden shrink-0 xl:block">
          <svg width={260} height={44} className="overflow-visible">
            <defs>
              <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity="0.25" />
                <stop offset="100%" stopColor={color} stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={path.area} fill="url(#spark-fill)" />
            <path d={path.line} fill="none" stroke={color} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
    </section>
  );
}

function buildPath(series: number[], w: number, h: number) {
  if (series.length === 0) return { line: "", area: "" };
  const step = w / Math.max(series.length - 1, 1);
  const pts = series.map((v, i) => {
    const x = i * step;
    const y = h - ((v + 1) / 2) * h;
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  return { line, area };
}
