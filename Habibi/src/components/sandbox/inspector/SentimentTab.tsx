import { LineChart, Line, ResponsiveContainer, YAxis, XAxis, ReferenceLine, Tooltip } from "recharts";
import { TrendingDown, TrendingUp, Minus } from "lucide-react";
import type { SandboxTurn } from "@/data/sandbox-seed";
import type { TurnAnalysisEvent } from "../voice/liveEvents";

/**
 * Customer sentiment over the call.
 *
 * On a live call the score is computed server-side and arrives over RTVI; the
 * voice transcript the browser receives carries no sentiment at all, so this
 * tab used to show its empty state for the entire call. Rehearsal turns still
 * carry their own score, and that path is unchanged.
 */
export function SentimentTab({
  turns,
  analysis = [],
}: {
  turns: SandboxTurn[];
  analysis?: TurnAnalysisEvent[];
}) {
  const livePoints = analysis
    .filter((t) => t.speaker === "customer" && typeof t.sentiment === "number")
    .map((t, i) => ({ turn: i + 1, sentiment: t.sentiment as number }));
  const points = livePoints.length
    ? livePoints
    : turns
        .filter((t) => t.role === "customer" && typeof t.sentiment === "number")
        .map((t, i) => ({ turn: i + 1, sentiment: t.sentiment as number }));

  if (points.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
        Sentiment appears once the customer speaks.
      </div>
    );
  }

  const last = points[points.length - 1].sentiment;
  const prev = points[points.length - 2]?.sentiment ?? last;
  const delta = last - prev;
  const Icon = delta > 0.05 ? TrendingUp : delta < -0.05 ? TrendingDown : Minus;
  const trendColor = delta > 0.05 ? "text-text-success" : delta < -0.05 ? "text-text-danger" : "text-text-subtlest";

  return (
    <div className="space-y-150">
      <div className="flex items-center gap-150 rounded-medium border border-border bg-surface-sunken p-150">
        <div>
          <div className="text-body-small text-text-subtlest">Current</div>
          <div className="text-[1.25rem] font-semibold text-text">{last.toFixed(2)}</div>
        </div>
        <div className={`ml-auto inline-flex items-center gap-050 text-body-small ${trendColor}`}>
          <Icon className="h-3.5 w-3.5" />
          {delta >= 0 ? "+" : ""}{delta.toFixed(2)}
        </div>
      </div>
      <div className="h-40 w-full">
        <ResponsiveContainer>
          <LineChart data={points} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <XAxis dataKey="turn" tick={{ fontSize: 10 }} />
            <YAxis domain={[-1, 1]} tick={{ fontSize: 10 }} />
            <ReferenceLine y={0} stroke="var(--border)" />
            <Tooltip contentStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="sentiment" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="text-body-small text-text-subtlest">−1 hostile · 0 neutral · +1 delighted</div>
    </div>
  );
}
