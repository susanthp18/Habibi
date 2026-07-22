import { LineChart, Line, ResponsiveContainer, YAxis, XAxis, ReferenceLine, Tooltip } from "recharts";
import { TrendingDown, TrendingUp, Minus } from "lucide-react";
import type { SandboxTurn } from "@/data/sandbox-seed";

export function SentimentTab({ turns }: { turns: SandboxTurn[] }) {
  const points = turns
    .filter((t) => t.role === "customer" && typeof t.sentiment === "number")
    .map((t, i) => ({ turn: i + 1, sentiment: t.sentiment as number }));

  if (points.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
        Sentiment appears once the customer speaks.
      </div>
    );
  }

  const last = points[points.length - 1].sentiment;
  const prev = points[points.length - 2]?.sentiment ?? last;
  const delta = last - prev;
  const Icon = delta > 0.05 ? TrendingUp : delta < -0.05 ? TrendingDown : Minus;
  const trendColor = delta > 0.05 ? "text-emerald-600" : delta < -0.05 ? "text-red-600" : "text-text-muted";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 rounded-md border border-[var(--border-token)] bg-surface-sunken p-3">
        <div>
          <div className="text-[10.5px] uppercase tracking-wide text-text-muted">Current</div>
          <div className="text-[20px] font-semibold text-text-primary">{last.toFixed(2)}</div>
        </div>
        <div className={`ml-auto inline-flex items-center gap-1 text-[12px] ${trendColor}`}>
          <Icon className="h-3.5 w-3.5" />
          {delta >= 0 ? "+" : ""}{delta.toFixed(2)}
        </div>
      </div>
      <div className="h-40 w-full">
        <ResponsiveContainer>
          <LineChart data={points} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <XAxis dataKey="turn" tick={{ fontSize: 10 }} />
            <YAxis domain={[-1, 1]} tick={{ fontSize: 10 }} />
            <ReferenceLine y={0} stroke="var(--border-token)" />
            <Tooltip contentStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="sentiment" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="text-[11px] text-text-muted">−1 hostile · 0 neutral · +1 delighted</div>
    </div>
  );
}
