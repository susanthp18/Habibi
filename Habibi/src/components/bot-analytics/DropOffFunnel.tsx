type FunnelStage = { id: string; label: string; count: number };

export function DropOffFunnel({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(1, stages[0]?.count ?? 0);
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-150 py-100">
        <div className="text-body font-semibold text-text">Drop-off funnel</div>
        <div className="text-body-small text-text-subtlest">Where sessions leak between stages</div>
      </div>
      <div className="space-y-075 p-150">
        {stages.map((s, i) => {
          const prev = stages[i - 1];
          const drop = prev ? prev.count - s.count : 0;
          const dropPct = prev && prev.count > 0 ? (drop / prev.count) * 100 : 0;
          return (
            <div key={s.id}>
              <div className="flex items-center justify-between text-body-small">
                <span className="font-medium text-text">{s.label}</span>
                <span className="text-text-subtle">
                  {s.count.toLocaleString()}
                  {prev && (
                    <span className="ml-100 text-text-danger-bolder">−{drop.toLocaleString()} ({dropPct.toFixed(1)}%)</span>
                  )}
                </span>
              </div>
              <div className="mt-050 h-300 overflow-hidden rounded bg-surface-sunken">
                <div
                  className="h-full bg-background-brand-bold transition-all"
                  style={{ width: `${(s.count / max) * 100}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
