import { funnelStages } from "@/data/bot-analytics-seed";

export function DropOffFunnel() {
  const max = funnelStages[0]?.count ?? 1;
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[13px] font-semibold text-brand-navy">Drop-off funnel</div>
        <div className="text-[11px] text-text-muted">Where sessions leak between stages</div>
      </div>
      <div className="space-y-1.5 p-3">
        {funnelStages.map((s, i) => {
          const prev = funnelStages[i - 1];
          const drop = prev ? prev.count - s.count : 0;
          const dropPct = prev ? (drop / prev.count) * 100 : 0;
          return (
            <div key={s.id}>
              <div className="flex items-center justify-between text-[12px]">
                <span className="font-medium text-brand-navy">{s.label}</span>
                <span className="text-text-secondary">
                  {s.count.toLocaleString()}
                  {prev && (
                    <span className="ml-2 text-red-700">−{drop.toLocaleString()} ({dropPct.toFixed(1)}%)</span>
                  )}
                </span>
              </div>
              <div className="mt-1 h-6 overflow-hidden rounded bg-surface-sunken">
                <div
                  className="h-full bg-brand-primary transition-all"
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
