import { ChartCard, SnapshotPill } from "@/components/charts";

type FunnelStage = { id: string; label: string; count: number };

export function DropOffFunnel({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(1, stages[0]?.count ?? 0);
  return (
    <ChartCard
      title="Drop-off funnel"
      subtitle="Where sessions leak between stages"
      action={<SnapshotPill />}
    >
      <div className="space-y-100">
        {stages.map((s, i) => {
          const prev = stages[i - 1];
          const drop = prev ? prev.count - s.count : 0;
          const dropPct = prev && prev.count > 0 ? (drop / prev.count) * 100 : 0;
          const width = (s.count / max) * 100;
          return (
            <div key={s.id}>
              <div className="flex items-center justify-between text-body-small">
                <span className="font-medium text-text">{s.label}</span>
                <span className="tabular-nums text-text-subtle">
                  {s.count.toLocaleString()}
                  {prev ? (
                    <span className="ml-100 text-text-danger-bolder">
                      −{drop.toLocaleString()} ({dropPct.toFixed(1)}%)
                    </span>
                  ) : null}
                </span>
              </div>
              <div className="mt-050 h-3 overflow-hidden rounded-full bg-surface-sunken p-0.5">
                <div
                  className="h-full rounded-full bg-background-brand-bold transition-[width] duration-300"
                  style={{
                    width: `${width}%`,
                    opacity: 1 - i * 0.12,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}
