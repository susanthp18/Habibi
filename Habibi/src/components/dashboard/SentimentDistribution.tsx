type Props = {
  positive: number;
  neutral: number;
  negative: number;
};

export function SentimentDistribution({ positive, neutral, negative }: Props) {
  const total = positive + neutral + negative || 1;
  const p = (positive / total) * 100;
  const n = (neutral / total) * 100;
  const g = (negative / total) * 100;

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface-card p-4 shadow-card">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-brand-navy">Sentiment distribution</h3>
        <p className="text-xs text-text-secondary">Aggregated across every call in period</p>
      </div>

      <div className="flex h-8 w-full overflow-hidden rounded-md border border-border">
        <div
          className="flex items-center justify-center text-xs font-semibold text-white"
          style={{ width: `${p}%`, background: "var(--sentiment-positive)" }}
        >
          {p.toFixed(0)}%
        </div>
        <div
          className="flex items-center justify-center text-xs font-semibold text-brand-navy"
          style={{ width: `${n}%`, background: "var(--sentiment-neutral)" }}
        >
          {n.toFixed(0)}%
        </div>
        <div
          className="flex items-center justify-center text-xs font-semibold text-white"
          style={{ width: `${g}%`, background: "var(--sentiment-negative)" }}
        >
          {g.toFixed(0)}%
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
        <Legend color="var(--sentiment-positive)" label="Positive" value={`${p.toFixed(1)}%`} sub={`${positive.toLocaleString()} calls`} />
        <Legend color="var(--sentiment-neutral)" label="Neutral" value={`${n.toFixed(1)}%`} sub={`${neutral.toLocaleString()} calls`} />
        <Legend color="var(--sentiment-negative)" label="Negative" value={`${g.toFixed(1)}%`} sub={`${negative.toLocaleString()} calls`} />
      </div>

      <div className="mt-auto pt-4 text-[11px] text-text-muted">
        Positive share ↑ correlates with recovery rate ↑ and PTP kept-rate ↑.
      </div>
    </div>
  );
}

function Legend({ color, label, value, sub }: { color: string; label: string; value: string; sub: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-sunken px-2.5 py-2">
      <div className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full" style={{ background: color }} />
        <span className="text-[11px] text-text-secondary">{label}</span>
      </div>
      <div className="mt-0.5 text-sm font-semibold text-brand-navy tabular">{value}</div>
      <div className="text-[10px] text-text-muted tabular">{sub}</div>
    </div>
  );
}
