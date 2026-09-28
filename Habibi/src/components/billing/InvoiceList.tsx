import { useMemo, useState } from "react";
import { toast } from "sonner";
import type { Invoice } from "@/api/types/billing";
import { downloadInvoiceCsv, useInvoice, useInvoiceStatus } from "@/api/billing";
import { can, useMe } from "@/api/me";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/loading-state";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { inrCompact } from "@/lib/format";
import { Lozenge } from "@/components/ui/lozenge";
import {
  FilterTable,
  type FilterChip,
  type FilterTableColumn,
} from "@/components/records/FilterTable";

type InvoiceStatus = Invoice["status"];

const STATUS_DOT: Record<InvoiceStatus, string> = {
  paid: "var(--icon-accent-green)",
  pending: "var(--icon-accent-yellow)",
  draft: "var(--icon-accent-gray)",
};

export function InvoiceList({
  invoices,
  isLoading = false,
  isError = false,
  error,
}: {
  invoices: Invoice[];
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
}) {
  const [open, setOpen] = useState<string | null>(null);
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
            tone={
              inv.status === "paid" ? "success" : inv.status === "pending" ? "warning" : "neutral"
            }
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
      {
        id: "open",
        header: "",
        width: "0.5fr",
        className: "text-right",
        cell: (inv) => (
          <button
            type="button"
            className="text-body-small text-text-link underline"
            onClick={() => setOpen(inv.id)}
          >
            Lines
          </button>
        ),
      },
    ],
    [],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-100">
        <h3 className="text-body font-semibold text-text">Cost statements</h3>
        <p className="text-body-small text-text-subtle">
          Built on the 1st from last month&apos;s metered usage. A draft is rebuilt until issued.
        </p>
      </div>
      <FilterTable
        rows={invoices}
        getRowId={(inv) => inv.id}
        getStatus={(inv) => inv.status}
        chips={chips}
        columns={columns}
        isLoading={isLoading}
        isError={isError}
        error={error}
        errorLabel="invoices"
        emptyMessage="No statements yet. The first is built on the 1st of next month."
        ariaLabel="Invoice history"
        className="min-h-0 flex-1"
      />
      <InvoiceSheet invoiceId={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function InvoiceSheet({ invoiceId, onClose }: { invoiceId: string | null; onClose: () => void }) {
  const detail = useInvoice(invoiceId);
  const status = useInvoiceStatus();
  const me = useMe();
  const canWrite = can(me.data, "perm-billing-write");
  const d = detail.data;
  const move = (next: "pending" | "paid") =>
    void status
      .mutateAsync({ invoiceId: invoiceId!, status: next })
      .then(() => toast.success(next === "pending" ? "Statement issued" : "Marked paid"))
      .catch((err: Error) => toast.error(err.message));
  return (
    <Sheet open={!!invoiceId} onOpenChange={(v) => !v && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{d ? `${d.month} · ${d.env}` : "Cost statement"}</SheetTitle>
        </SheetHeader>
        {detail.isPending ? (
          <LoadingState label="Loading statement" />
        ) : !d ? (
          <p className="text-body-small text-text-danger">Could not load the statement.</p>
        ) : (
          <div className="mt-200 space-y-200 text-body-small">
            <table className="w-full">
              <thead className="text-text-subtlest">
                <tr>
                  <th className="text-left font-normal">Service</th>
                  <th className="text-right font-normal">Usage</th>
                  <th className="text-right font-normal">Amount</th>
                </tr>
              </thead>
              <tbody>
                {d.lines.map((l) => (
                  <tr key={l.serviceId} className="border-t border-border">
                    <td className="py-075 text-text">{l.serviceName}</td>
                    <td className="py-075 text-right tabular-nums text-text-subtle">
                      {l.units.toLocaleString(undefined, { maximumFractionDigits: 1 })} {l.unit}
                    </td>
                    <td className="py-075 text-right tabular-nums text-text">
                      {inrCompact(l.amountInr)}
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-border font-semibold">
                  <td className="py-075">Total</td>
                  <td />
                  <td className="py-075 text-right tabular-nums">{inrCompact(d.totalInr)}</td>
                </tr>
              </tbody>
            </table>
            <div className="flex flex-wrap gap-100">
              <Button onClick={() => void downloadInvoiceCsv(d.id)}>Download CSV</Button>
              {canWrite && d.status === "draft" ? (
                <Button
                  variant="primary"
                  disabled={status.isPending}
                  onClick={() => move("pending")}
                >
                  Issue (freeze the numbers)
                </Button>
              ) : null}
              {canWrite && d.status === "pending" ? (
                <Button variant="primary" disabled={status.isPending} onClick={() => move("paid")}>
                  Mark paid
                </Button>
              ) : null}
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
