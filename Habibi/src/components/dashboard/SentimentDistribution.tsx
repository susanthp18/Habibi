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
    <div className="flex h-full flex-col rounded-large border border-border bg-surface p-200">
      <div className="mb-150">
        <h3 className="text-sm font-semibold text-text">Sentiment distribution</h3>
        <p className="text-xs text-text-subtle">Aggregated across every call in period</p>
      </div>

      <div className="flex h-400 w-full overflow-hidden rounded-medium border border-border">
        <div
          className="flex items-center justify-center text-xs font-semibold text-white"
          style={{ width: `${p}%`, background: "var(--sentiment-positive)" }}
        >
          {p.toFixed(0)}%
        </div>
        <div
          className="flex items-center justify-center text-xs font-semibold text-text"
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

      <div className="mt-200 grid grid-cols-3 gap-150 text-xs">
        <Legend color="var(--sentiment-positive)" label="Positive" value={`${p.toFixed(1)}%`} sub={`${positive.toLocaleString()} calls`} />
        <Legend color="var(--sentiment-neutral)" label="Neutral" value={`${n.toFixed(1)}%`} sub={`${neutral.toLocaleString()} calls`} />
        <Legend color="var(--sentiment-negative)" label="Negative" value={`${g.toFixed(1)}%`} sub={`${negative.toLocaleString()} calls`} />
      </div>

      <div className="mt-auto pt-200 text-body-small text-text-subtlest">
        Positive share ↑ correlates with recovery rate ↑ and PTP kept-rate ↑.
      </div>
    </div>
  );
}

function Legend({ color, label, value, sub }: { color: string; label: string; value: string; sub: string }) {
  return (
    <div className="rounded-medium border border-border bg-surface-sunken px-150 py-100">
      <div className="flex items-center gap-075">
        <span className="h-100 w-100 rounded-full" style={{ background: color }} />
        <span className="text-body-small text-text-subtle">{label}</span>
      </div>
      <div className="mt-025 text-sm font-semibold text-text tabular">{value}</div>
      <div className="text-body-small text-text-subtlest tabular">{sub}</div>
    </div>
  );
}
