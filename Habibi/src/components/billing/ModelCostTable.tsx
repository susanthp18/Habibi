import { useMemo } from "react";

import type { BillingModelSpend } from "@/api/billing";
import { inrCompact } from "@/data/billing-seed";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

export function ModelCostTable({ rows }: { rows: BillingModelSpend[] }) {
  const total = useMemo(() => rows.reduce((acc, r) => acc + r.costInr, 0), [rows]);

  const columns = useMemo<RecordsColumn<BillingModelSpend>[]>(
    () => [
      {
        id: "model",
        header: "Model",
        sticky: true,
        sortable: true,
        sortValue: (r) => r.model,
        className: "min-w-[12rem]",
        cell: (r) => (
          <div className="flex min-w-0 items-center gap-075">
            <span
              aria-hidden
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: r.color }}
            />
            <span className="truncate text-body font-medium text-text">{r.model}</span>
          </div>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">models</span>
          </span>
        ),
      },
      {
        id: "service",
        header: "Service",
        sortable: true,
        sortValue: (r) => r.serviceName,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) => <span className="text-text-subtle">{r.serviceName}</span>,
      },
      {
        id: "source",
        header: "Source",
        sortable: true,
        sortValue: (r) => r.sourceRef ?? "",
        className: "min-w-[10rem] whitespace-nowrap",
        cell: (r) => (
          <span className="font-mono text-body-tiny text-text-subtle">{r.sourceRef || "—"}</span>
        ),
      },
      {
        id: "usage",
        header: "Usage",
        sortable: true,
        sortValue: (r) => r.units,
        align: "right",
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-text-subtle">
            {r.units >= 100 ? Math.round(r.units).toLocaleString("en-IN") : r.units.toFixed(2)}{" "}
            {r.unit}
          </span>
        ),
      },
      {
        id: "calls",
        header: "Calls",
        sortable: true,
        sortValue: (r) => r.calls,
        align: "right",
        className: "min-w-[5.5rem] whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-text-subtle">{r.calls.toLocaleString("en-IN")}</span>
        ),
        footer: (visible) => (
          <span className="tabular-nums">
            {visible.reduce((s, r) => s + r.calls, 0).toLocaleString("en-IN")}
          </span>
        ),
      },
      {
        id: "cost",
        header: "Spend",
        sortable: true,
        sortValue: (r) => r.costInr,
        align: "right",
        className: "min-w-[6rem] whitespace-nowrap",
        cell: (r) => <span className="tabular-nums text-text">{inrCompact(r.costInr)}</span>,
        footer: (visible) => (
          <span className="font-semibold tabular-nums text-text">
            {inrCompact(visible.reduce((s, r) => s + r.costInr, 0))}
          </span>
        ),
      },
      {
        id: "share",
        header: "Share",
        sortable: true,
        sortValue: (r) => (total > 0 ? (r.costInr / total) * 100 : 0),
        align: "right",
        className: "min-w-[5rem] whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-text-subtlest">
            {(total > 0 ? (r.costInr / total) * 100 : 0).toFixed(1)}%
          </span>
        ),
      },
    ],
    [total],
  );

  return (
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-100">
        <h3 className="text-body font-semibold text-text">Cost breakdown by model</h3>
        <p className="text-body-small text-text-subtle">
          Mouth LLM rows show <span className="font-mono">llm_gateway.voice</span> when the gateway
          flag is on; otherwise <span className="font-mono">azure_openai.chat_with_tools</span>.
        </p>
      </div>
      <RecordsTable
        rows={rows}
        getRowId={(r) => `${r.serviceId}-${r.model}-${r.sourceRef ?? ""}`}
        columns={columns}
        defaultSort={{ id: "cost", dir: -1 }}
        ariaLabel="Cost breakdown by model"
        tableClassName="min-w-[48rem]"
        className="rounded-none border-0"
        emptyMessage="No per-model usage in this window. Calls handled before per-call metering was enabled carry no model dimension."
      />
    </div>
  );
}
