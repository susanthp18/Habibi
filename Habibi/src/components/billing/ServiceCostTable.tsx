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
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-200 py-100">
        <div>
          <h3 className="text-body font-semibold text-text">Cost breakdown by service</h3>
          <p className="text-body-small text-text-subtle">
            Sorted by {sort === "cost" ? "spend" : sort === "share" ? "share" : "period-over-period change"}
          </p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-body-small">
          <thead>
            <tr className="border-b border-border text-left text-body-small font-semibold text-text-subtlest">
              <th className="px-200 py-100">Service</th>
              <th className="px-150 py-100">Category</th>
              <th className="px-150 py-100 text-right">Usage</th>
              <th className="px-150 py-100 text-right">Unit cost</th>
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
                  className="cursor-pointer border-b border-border transition-colors hover:bg-surface-sunken"
                >
                  <td className="px-200 py-150">
                    <div className="flex items-center gap-100">
                      <span className="h-2.5 w-2.5 rounded-small" style={{ backgroundColor: s.color }} />
                      <div>
                        <div className="font-medium text-text">{s.name}</div>
                        <div className="text-body-small text-text-subtlest">{s.provider}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-150 py-150 text-text-subtle">{s.category}</td>
                  <td className="px-150 py-150 text-right font-mono">
                    {units >= 1000 ? `${(units / 1000).toFixed(1)}k` : units.toFixed(1)}
                    <span className="ml-050 text-body-small text-text-subtlest">{s.unit}</span>
                  </td>
                  <td className="px-150 py-150 text-right font-mono text-text-subtle">
                    {inr(s.unitCostInr)}
                  </td>
                  <td className="px-150 py-150 text-right font-semibold text-text">
                    {inrCompact(cost)}
                  </td>
                  <td className="px-150 py-150 text-right">
                    <span
                      className={cn(
                        "inline-flex items-center gap-025 rounded px-075 py-025 text-body-small font-semibold",
                        delta >= 0 ? "bg-background-danger-subtler text-text-danger-bolder" : "bg-background-success-subtler text-text-success-bolder",
                      )}
                    >
                      {delta >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                      {Math.abs(delta).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-150 py-150">
                    <div className="ml-auto flex items-center justify-end gap-100">
                      <div className="h-1.5 w-1000 overflow-hidden rounded-full bg-surface-sunken">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${Math.min(100, share)}%`, backgroundColor: s.color }}
                        />
                      </div>
                      <span className="w-400 text-right font-mono text-body-small text-text-subtlest">
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
    <th className="px-150 py-100 text-right">
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "inline-flex items-center gap-050",
          active ? "text-text-brand" : "text-text-subtlest hover:text-text-brand",
        )}
      >
        {label}
      </button>
    </th>
  );
}
