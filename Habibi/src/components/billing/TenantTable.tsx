import { useMemo } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import type { BillingTenantBreakdown } from "@/api/billing";
import { inrCompact } from "@/data/billing-seed";
import { cn } from "@/lib/utils";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

function deltaPct(r: BillingTenantBreakdown) {
  return r.spendPrev > 0 ? ((r.spend - r.spendPrev) / r.spendPrev) * 100 : r.spend > 0 ? 100 : 0;
}

export function TenantTable({ rows }: { rows: BillingTenantBreakdown[] }) {
  const columns = useMemo<RecordsColumn<BillingTenantBreakdown>[]>(
    () => [
      {
        id: "tenant",
        header: "Tenant",
        sticky: true,
        sortable: true,
        sortValue: (r) => r.name,
        className: "min-w-[10rem]",
        cell: (r) => <span className="truncate font-medium text-text">{r.name}</span>,
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">tenants</span>
          </span>
        ),
      },
      {
        id: "resolved",
        header: "Resolved calls",
        sortable: true,
        sortValue: (r) => r.resolvedCalls,
        align: "right",
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-text">{r.resolvedCalls.toLocaleString("en-IN")}</span>
        ),
        footer: (visible) => (
          <span className="tabular-nums">
            {visible.reduce((s, r) => s + r.resolvedCalls, 0).toLocaleString("en-IN")}
          </span>
        ),
      },
      {
        id: "aht",
        header: "AHT",
        sortable: true,
        sortValue: (r) => r.ahtSec,
        align: "right",
        className: "min-w-[5.5rem] whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-text-subtle">
            {Math.floor(r.ahtSec / 60)}m {r.ahtSec % 60}s
          </span>
        ),
      },
      {
        id: "spend",
        header: "Spend",
        sortable: true,
        sortValue: (r) => r.spend,
        align: "right",
        className: "min-w-[6rem] whitespace-nowrap",
        cell: (r) => <span className="font-semibold tabular-nums text-text">{inrCompact(r.spend)}</span>,
        footer: (visible) => (
          <span className="font-semibold tabular-nums text-text">
            {inrCompact(visible.reduce((s, r) => s + r.spend, 0))}
          </span>
        ),
      },
      {
        id: "costPerCall",
        header: "Cost / call",
        sortable: true,
        sortValue: (r) => r.costPerCall,
        align: "right",
        className: "min-w-[6.5rem] whitespace-nowrap",
        cell: (r) => <span className="tabular-nums text-text">₹{r.costPerCall.toFixed(1)}</span>,
      },
      {
        id: "delta",
        header: "Δ",
        sortable: true,
        sortValue: (r) => deltaPct(r),
        align: "right",
        className: "min-w-[6.5rem] whitespace-nowrap",
        cell: (r) => {
          const delta = deltaPct(r);
          return (
            <span
              className={cn(
                "inline-flex items-center gap-025 rounded px-075 py-025 text-body-small font-semibold",
                delta >= 0
                  ? "bg-background-danger-subtler text-text-danger-bolder"
                  : "bg-background-success-subtler text-text-success-bolder",
              )}
            >
              {delta >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
              {Math.abs(delta).toFixed(1)}%
            </span>
          );
        },
      },
      {
        id: "budget",
        header: "Budget",
        sortable: true,
        sortValue: (r) => r.budgetPct,
        align: "right",
        className: "min-w-[8rem]",
        cell: (r) => (
          <div className="ml-auto flex items-center justify-end gap-100">
            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
              <div
                className={cn(
                  "h-full rounded-full",
                  r.budgetPct < 70 && "bg-background-success-bold",
                  r.budgetPct >= 70 && r.budgetPct < 100 && "bg-background-warning-bold",
                  r.budgetPct >= 100 && "bg-background-danger-bold",
                )}
                style={{ width: `${Math.min(100, r.budgetPct)}%` }}
              />
            </div>
            <span className="w-500 text-right text-body-small tabular-nums text-text-subtlest">
              {Math.round(r.budgetPct)}%
            </span>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-100">
        <h3 className="text-body font-semibold text-text">Per-tenant breakdown</h3>
        <p className="text-body-small text-text-subtle">Spend and unit economics per client account</p>
      </div>
      <RecordsTable
        rows={rows}
        getRowId={(r) => r.id}
        columns={columns}
        defaultSort={{ id: "spend", dir: -1 }}
        ariaLabel="Per-tenant billing breakdown"
        tableClassName="min-w-[48rem]"
        className="rounded-none border-0"
        emptyMessage="No tenant spend in this window."
        rowClassName={(r) => (r.budgetPct > 100 ? "bg-background-danger hover:bg-background-danger" : undefined)}
      />
    </div>
  );
}
