import { useMemo } from "react";
import { inrCompact, type Invoice } from "@/data/billing-seed";
import { Lozenge } from "@/components/ui/lozenge";
import { FilterTable, type FilterChip, type FilterTableColumn } from "@/components/records/FilterTable";

type InvoiceStatus = Invoice["status"];

const STATUS_DOT: Record<InvoiceStatus, string> = {
  paid: "var(--icon-accent-green)",
  pending: "var(--icon-accent-yellow)",
  draft: "var(--icon-accent-gray)",
};

export function InvoiceList({ invoices }: { invoices: Invoice[] }) {
  const chips = useMemo<FilterChip<InvoiceStatus>[]>(() => {
    const counts = { paid: 0, pending: 0, draft: 0 };
    for (const inv of invoices) counts[inv.status] += 1;
    return [
      { key: "all", label: "All", count: invoices.length },
      { key: "paid", label: "Paid", dot: STATUS_DOT.paid, count: counts.paid },
      { key: "pending", label: "Pending", dot: STATUS_DOT.pending, count: counts.pending },
      { key: "draft", label: "Draft", dot: STATUS_DOT.draft, count: counts.draft },
    ];
  }, [invoices]);

  const columns = useMemo<FilterTableColumn<Invoice>[]>(
    () => [
      {
        id: "month",
        header: "Cycle",
        width: "1.4fr",
        cell: (inv) => (
          <div className="min-w-0">
            <div className="truncate font-semibold text-text">{inv.month}</div>
            <div className="truncate text-body-small text-text-subtlest">{inv.id}</div>
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        width: "0.8fr",
        cell: (inv) => (
          <Lozenge
            tone={inv.status === "paid" ? "success" : inv.status === "pending" ? "warning" : "neutral"}
            className="capitalize"
          >
            {inv.status}
          </Lozenge>
        ),
      },
      {
        id: "amount",
        header: "Amount",
        width: "0.9fr",
        className: "text-right",
        cell: (inv) => (
          <span className="tabular-nums font-semibold text-text">
            {inv.amountInr > 0 ? inrCompact(inv.amountInr) : "—"}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-100">
        <h3 className="text-body font-semibold text-text">Invoice history</h3>
        <p className="text-body-small text-text-subtle">Production billing cycles</p>
      </div>
      <FilterTable
        rows={invoices}
        getRowId={(inv) => inv.id}
        getStatus={(inv) => inv.status}
        chips={chips}
        columns={columns}
        emptyMessage="No invoices yet."
        ariaLabel="Invoice history"
        className="min-h-0 flex-1"
      />
    </div>
  );
}
