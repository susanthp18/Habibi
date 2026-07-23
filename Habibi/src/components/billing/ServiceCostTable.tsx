import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import {
  changePct,
  inr,
  inrCompact,
  sumRange,
  usageUnits,
  type DayPoint,
  type Service,
} from "@/data/billing-seed";
import { cn } from "@/lib/utils";

type SortKey = "cost" | "share" | "delta";

export function ServiceCostTable({
  services,
  current,
  previous,
  onRowClick,
}: {
  services: Service[];
  current: DayPoint[];
  previous: DayPoint[];
  onRowClick: (s: Service) => void;
}) {
  const [sort, setSort] = useState<SortKey>("cost");

  const totalCur = sumRange(current);
  const rows = useMemo(() => {
    const arr = services.map((s) => {
      const cost = sumRange(current, s.id);
      const prev = sumRange(previous, s.id);
      const delta = changePct(cost, prev);
      const share = totalCur > 0 ? (cost / totalCur) * 100 : 0;
      return { s, cost, prev, delta, share };
    });
    arr.sort((a, b) => {
      if (sort === "cost") return b.cost - a.cost;
      if (sort === "share") return b.share - a.share;
      return b.delta - a.delta;
    });
    return arr;
  }, [services, current, previous, sort, totalCur]);

  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-4 py-2">
        <div>
          <h3 className="text-[13px] font-semibold text-brand-navy">Cost breakdown by service</h3>
          <p className="text-[11px] text-text-secondary">
            Sorted by {sort === "cost" ? "spend" : sort === "share" ? "share" : "period-over-period change"}
          </p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--border-token)] text-left text-[10.5px] font-semibold uppercase tracking-wider text-text-muted">
              <th className="px-4 py-2">Service</th>
              <th className="px-3 py-2">Category</th>
              <th className="px-3 py-2 text-right">Usage</th>
              <th className="px-3 py-2 text-right">Unit cost</th>
              <SortableTh label="Cost" active={sort === "cost"} onClick={() => setSort("cost")} />
              <SortableTh label="Δ vs prev" active={sort === "delta"} onClick={() => setSort("delta")} />
              <SortableTh label="Share" active={sort === "share"} onClick={() => setSort("share")} />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ s, cost, delta, share }) => {
              const units = usageUnits(cost, s.unitCostInr);
              return (
                <tr
                  key={s.id}
                  onClick={() => onRowClick(s)}
                  className="cursor-pointer border-b border-[var(--border-token)] transition-colors hover:bg-surface-sunken"
                >
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
                      <div>
                        <div className="font-medium text-brand-navy">{s.name}</div>
                        <div className="text-[10.5px] text-text-muted">{s.provider}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-text-secondary">{s.category}</td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {units >= 1000 ? `${(units / 1000).toFixed(1)}k` : units.toFixed(1)}
                    <span className="ml-1 text-[10.5px] text-text-muted">{s.unit}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-secondary">
                    {inr(s.unitCostInr)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-semibold text-brand-navy">
                    {inrCompact(cost)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <span
                      className={cn(
                        "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10.5px] font-semibold",
                        delta >= 0 ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700",
                      )}
                    >
                      {delta >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                      {Math.abs(delta).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="ml-auto flex items-center justify-end gap-2">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-sunken">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${Math.min(100, share)}%`, backgroundColor: s.color }}
                        />
                      </div>
                      <span className="w-8 text-right font-mono text-[11px] text-text-muted">
                        {share.toFixed(0)}%
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SortableTh({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <th className="px-3 py-2 text-right">
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "inline-flex items-center gap-1 uppercase tracking-wider",
          active ? "text-brand-primary" : "text-text-muted hover:text-brand-primary",
        )}
      >
        {label}
      </button>
    </th>
  );
}
