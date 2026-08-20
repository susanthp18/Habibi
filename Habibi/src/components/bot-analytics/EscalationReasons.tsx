import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import type { EscalationReason } from "@/data/bot-analytics-seed";
import { ChartCard, ModernDonut, SnapshotPill } from "@/components/charts";

const COLORS = ["#357de8", "#82b536", "#bf63f3", "#f68909", "#1558bc", "#964ac0", "#42b2d7"];

export function EscalationReasons({ reasons }: { reasons: EscalationReason[] }) {
  const total = reasons.reduce((a, r) => a + r.count, 0);
  const slices = reasons.map((r, i) => ({
    name: r.label,
    value: r.count,
    color: COLORS[i % COLORS.length],
  }));

  return (
    <ChartCard
      title="Escalation reasons"
      subtitle={`${total.toLocaleString()} escalations · trend vs prior period`}
      action={<SnapshotPill />}
    >
      <div className="grid gap-150 md:grid-cols-[180px_1fr]">
        <div className="mx-auto">
          <ModernDonut
            data={slices}
            centerValue={total.toLocaleString()}
            centerLabel="Total"
            size={160}
            thickness={16}
          />
        </div>
        <ul className="space-y-050 text-body-small">
          {reasons.map((r, i) => {
            const pct = total ? (r.count / total) * 100 : 0;
            const Trend = r.trendDelta > 1 ? ArrowUp : r.trendDelta < -1 ? ArrowDown : Minus;
            const bad = r.trendDelta > 1;
            return (
              <li key={r.id} className="flex items-center gap-100">
                <span className="inline-block size-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="flex-1 truncate text-text">{r.label}</span>
                <span className="tabular-nums text-text-subtle">{r.count}</span>
                <span className="w-500 text-right tabular-nums text-text-subtlest">{pct.toFixed(0)}%</span>
                <span
                  className={`inline-flex w-14 items-center justify-end gap-025 text-body-small ${
                    bad
                      ? "text-text-danger-bolder"
                      : r.trendDelta < -1
                        ? "text-text-success-bolder"
                        : "text-text-subtlest"
                  }`}
                >
                  <Trend className="h-3 w-3" />
                  {Math.abs(r.trendDelta)}%
                </span>
              </li>
            );
          })}
          {!reasons.length && <li className="text-text-subtlest">No escalations in this range.</li>}
        </ul>
      </div>
    </ChartCard>
  );
}
