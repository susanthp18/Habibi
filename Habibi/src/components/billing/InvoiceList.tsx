import { Download, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { INVOICES, inrCompact } from "@/data/billing-seed";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export function InvoiceList() {
  return (
    <div className="flex flex-col rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-4 py-2">
        <h3 className="text-[13px] font-semibold text-brand-navy">Invoice history</h3>
        <p className="text-[11px] text-text-secondary">Last 6 billing cycles</p>
      </div>
      <div className="divide-y divide-[var(--border-token)]">
        {INVOICES.map((inv) => (
          <div key={inv.id} className="flex items-center gap-3 px-4 py-3 text-[12px]">
            <div className="w-24 shrink-0">
              <div className="font-semibold text-brand-navy">{inv.month}</div>
              <div className="font-mono text-[10.5px] text-text-muted">{inv.id}</div>
            </div>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10.5px] font-semibold capitalize",
                inv.status === "paid" && "bg-emerald-100 text-emerald-700",
                inv.status === "pending" && "bg-amber-100 text-amber-700",
                inv.status === "draft" && "bg-slate-100 text-slate-700",
              )}
            >
              {inv.status}
            </span>
            <span className="ml-auto font-mono font-semibold text-brand-navy">
              {inv.amountInr > 0 ? inrCompact(inv.amountInr) : "—"}
            </span>
            <div className="flex gap-1">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => toast.success(`Opened ${inv.id}`)}
                disabled={inv.status === "draft"}
              >
                <FileText className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => toast.success(`Downloading ${inv.id}.pdf`)}
                disabled={inv.status === "draft"}
              >
                <Download className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
