import { inrCompact, type Invoice } from "@/data/billing-seed";
import { Lozenge } from "@/components/ui/lozenge";

export function InvoiceList({ invoices }: { invoices: Invoice[] }) {
  return (
    <div className="flex h-full flex-col rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-100">
        <h3 className="text-body font-semibold text-text">Invoice history</h3>
        <p className="text-body-small text-text-subtle">Production billing cycles</p>
      </div>
      <div className="divide-y divide-border">
        {invoices.length === 0 ? (
          <div className="px-200 py-300 text-body-small text-text-subtlest">No invoices yet.</div>
        ) : (
          invoices.map((inv) => (
            <div key={inv.id} className="flex items-center gap-150 px-200 py-150 text-body-small">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-text">{inv.month}</div>
                <div className="font-mono text-body-small text-text-subtlest">{inv.id}</div>
              </div>
              <Lozenge
                tone={
                  inv.status === "paid" ? "success" : inv.status === "pending" ? "warning" : "neutral"
                }
                className="capitalize"
              >
                {inv.status}
              </Lozenge>
              <span className="w-1000 text-right font-mono font-semibold text-text">
                {inv.amountInr > 0 ? inrCompact(inv.amountInr) : "—"}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
