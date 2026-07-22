import { FileText, Mail, MessageCircle, PhoneCall } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Channel, Customer, DocStatus } from "@/data/customer360-seed";
import { fmtDate } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<DocStatus, string> = {
  requested: "bg-surface-sunken text-text-secondary",
  generating: "bg-warning-bg text-warning",
  sent: "bg-success-bg text-success",
  failed: "bg-danger-bg text-danger",
};

const CHANNEL_ICON: Partial<Record<Channel, React.ComponentType<{ className?: string }>>> = {
  voice: PhoneCall,
  whatsapp: MessageCircle,
  chat: MessageCircle,
  email: Mail,
};

export function DocumentsTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-brand-navy">Document fulfillment</div>
          <div className="text-xs text-text-secondary">Bot captures the request, back-office (or bot) sends the file.</div>
        </div>
        <Button onClick={onCreate}>
          <FileText className="h-3.5 w-3.5" />
          Send statement
        </Button>
      </div>

      {customer.documents.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-surface-card p-10 text-center text-sm text-text-muted">
          No documents requested yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface-card">
          <table className="w-full text-sm">
            <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-secondary">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Type</th>
                <th className="px-4 py-2 text-left font-medium">Requested via</th>
                <th className="px-4 py-2 text-left font-medium">Requested on</th>
                <th className="px-4 py-2 text-left font-medium">Delivered via</th>
                <th className="px-4 py-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {customer.documents.map((d) => {
                const InIcon = CHANNEL_ICON[d.requestedVia] ?? MessageCircle;
                const OutIcon = d.deliveryChannel === "email" ? Mail : MessageCircle;
                return (
                  <tr key={d.id} className="border-t border-border hover:bg-brand-tint/30">
                    <td className="px-4 py-2.5 text-sm text-text-primary">{d.type}</td>
                    <td className="px-4 py-2.5 text-xs text-text-secondary">
                      <span className="inline-flex items-center gap-1 capitalize">
                        <InIcon className="h-3 w-3" /> {d.requestedVia}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-text-secondary tabular">{fmtDate(d.requestedAt)}</td>
                    <td className="px-4 py-2.5 text-xs text-text-secondary">
                      <span className="inline-flex items-center gap-1 capitalize">
                        <OutIcon className="h-3 w-3" /> {d.deliveryChannel}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase", STATUS_TONE[d.status])}>{d.status}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
