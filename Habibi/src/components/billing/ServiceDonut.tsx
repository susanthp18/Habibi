import {
  CATEGORY_COLORS,
  sumRange,
  inrCompact,
  type DayPoint,
  type Service,
  type ServiceCategory,
} from "@/data/billing-seed";
import { ChartCard, ModernDonut, SnapshotPill } from "@/components/charts";

export function ServiceDonut({ data, services }: { data: DayPoint[]; services: Service[] }) {
  const totals: Record<ServiceCategory, number> = { LLM: 0, Voice: 0, Messaging: 0, Infra: 0 };
  for (const s of services) {
    totals[s.category] += sumRange(data, s.id);
  }
  const rows = (Object.keys(totals) as ServiceCategory[])
    .map((k) => ({
      name: k,
      value: totals[k],
      color: CATEGORY_COLORS[k],
    }))
    .filter((r) => r.value > 0);
  const grand = rows.reduce((a, r) => a + r.value, 0);

  return (
    <ChartCard
      title="Share by category"
      subtitle="LLM · Voice · Messaging · Infra"
      className="min-h-[17.5rem]"
      action={<SnapshotPill />}
    >
      <div className="flex min-h-0 flex-1 flex-col items-center gap-150">
        <ModernDonut
          data={rows}
          centerValue={inrCompact(grand)}
          centerLabel="Total"
          formatValue={inrCompact}
          size={168}
          thickness={16}
        />
        <div className="w-full space-y-075 text-body-small">
          {rows.map((r) => {
            const pct = grand > 0 ? Math.round((r.value / grand) * 100) : 0;
            return (
              <div key={r.name} className="flex items-center gap-100">
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: r.color }}
                />
                <span className="flex-1 font-medium text-text">{r.name}</span>
                <span className="font-mono text-text-subtle">{inrCompact(r.value)}</span>
                <span className="w-400 text-right text-body-small text-text-subtlest">{pct}%</span>
              </div>
            );
          })}
          {rows.length === 0 && (
            <p className="text-body-small text-text-subtlest">No spend in this period.</p>
          )}
        </div>
      </div>
    </ChartCard>
  );
}
