import { useMemo } from "react";
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
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

type ServiceRow = {
  s: Service;
  cost: number;
  prev: number;
  delta: number;
  share: number;
};

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
  const totalCur = sumRange(current);
  const rows = useMemo<ServiceRow[]>(() => {
    return services.map((s) => {
      const cost = sumRange(current, s.id);
      const prev = sumRange(previous, s.id);
      const delta = changePct(cost, prev);
      const share = totalCur > 0 ? (cost / totalCur) * 100 : 0;
      return { s, cost, prev, delta, share };
    });
  }, [services, current, previous, totalCur]);

  const columns = useMemo<RecordsColumn<ServiceRow>[]>(
    () => [
      {
        id: "service",
        header: "Service",
        sticky: true,
        sortable: true,
        sortValue: (r) => r.s.name,
        className: "min-w-[12rem]",
        cell: (r) => (
          <div className="flex min-w-0 items-center gap-100">
            <span className="h-2.5 w-2.5 shrink-0 rounded-small" style={{ backgroundColor: r.s.color }} />
            <span className="min-w-0">
              <span className="block truncate text-body font-medium text-text">{r.s.name}</span>
              <span className="block truncate text-body-small text-text-subtlest">{r.s.provider}</span>
            </span>
          </div>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">services</span>
          </span>
        ),
      },
      {
        id: "category",
        header: "Category",
        sortable: true,
        sortValue: (r) => r.s.category,
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (r) => <RecordsTag name={r.s.category} />,
      },
      {
        id: "usage",
        header: "Usage",
        sortable: true,
        sortValue: (r) => usageUnits(r.cost, r.s.unitCostInr),
        align: "right",
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (r) => {
          const units = usageUnits(r.cost, r.s.unitCostInr);
          return (
            <span className="tabular-nums text-text">
              {units >= 1000 ? `${(units / 1000).toFixed(1)}k` : units.toFixed(1)}
              <span className="ml-050 text-body-small text-text-subtlest">{r.s.unit}</span>
            </span>
          );
        },
      },
      {
        id: "unitCost",
        header: "Unit cost",
        sortable: true,
        sortValue: (r) => r.s.unitCostInr,
        align: "right",
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (r) => <span className="tabular-nums text-text-subtle">{inr(r.s.unitCostInr)}</span>,
      },
      {
        id: "cost",
        header: "Cost",
        sortable: true,
        sortValue: (r) => r.cost,
        align: "right",
        className: "min-w-[6rem] whitespace-nowrap",
        cell: (r) => <span className="font-semibold tabular-nums text-text">{inrCompact(r.cost)}</span>,
        footer: (visible) => (
          <span className="font-semibold tabular-nums text-text">
            {inrCompact(visible.reduce((s, r) => s + r.cost, 0))}
          </span>
        ),
      },
      {
        id: "delta",
        header: "Δ vs prev",
        sortable: true,
        sortValue: (r) => r.delta,
        align: "right",
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (r) => (
          <span
            className={cn(
              "inline-flex items-center gap-025 rounded px-075 py-025 text-body-small font-semibold",
              r.delta >= 0
                ? "bg-background-danger-subtler text-text-danger-bolder"
                : "bg-background-success-subtler text-text-success-bolder",
            )}
          >
            {r.delta >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
            {Math.abs(r.delta).toFixed(1)}%
          </span>
        ),
      },
      {
        id: "share",
        header: "Share",
        sortable: true,
        sortValue: (r) => r.share,
        align: "right",
        className: "min-w-[8rem]",
        cell: (r) => (
          <div className="ml-auto flex items-center justify-end gap-100">
            <div className="h-1.5 w-1000 overflow-hidden rounded-full bg-surface-sunken">
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.min(100, r.share)}%`, backgroundColor: r.s.color }}
              />
            </div>
            <span className="w-400 text-right tabular-nums text-body-small text-text-subtlest">
              {r.share.toFixed(0)}%
            </span>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-100">
        <h3 className="text-body font-semibold text-text">Cost breakdown by service</h3>
        <p className="text-body-small text-text-subtle">Click a row for tenant mix and period change</p>
      </div>
      <RecordsTable
        rows={rows}
        getRowId={(r) => r.s.id}
        columns={columns}
        defaultSort={{ id: "cost", dir: -1 }}
        onRowClick={(r) => onRowClick(r.s)}
        ariaLabel="Cost breakdown by service"
        tableClassName="min-w-[52rem]"
        className="rounded-none border-0"
        emptyMessage="No service spend in this window."
      />
    </div>
  );
}
