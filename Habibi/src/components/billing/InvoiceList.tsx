import { inrCompact, type Invoice } from "@/data/billing-seed";
import { cn } from "@/lib/utils";

export function InvoiceList({ invoices }: { invoices: Invoice[] }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-4 py-2">
        <h3 className="text-[13px] font-semibold text-brand-navy">Invoice history</h3>
        <p className="text-[11px] text-text-secondary">Production billing cycles</p>
      </div>
      <div className="divide-y divide-[var(--border-token)]">
        {invoices.length === 0 ? (
          <div className="px-4 py-6 text-[12px] text-text-muted">No invoices yet.</div>
        ) : (
          invoices.map((inv) => (
            <div key={inv.id} className="flex items-center gap-3 px-4 py-3 text-[12px]">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-brand-navy">{inv.month}</div>
                <div className="font-mono text-[10.5px] text-text-muted">{inv.id}</div>
              </div>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10.5px] font-semibold capitalize",
                  inv.status === "paid" && "bg-emerald-100 text-emerald-700",
                  inv.status === "pending" && "bg-amber-100 text-amber-700",
                  inv.status === "draft" && "bg-surface-sunken text-text-secondary",
                )}
              >
                {inv.status}
              </span>
              <span className="w-20 text-right font-mono font-semibold text-brand-navy">
                {inv.amountInr > 0 ? inrCompact(inv.amountInr) : "—"}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
