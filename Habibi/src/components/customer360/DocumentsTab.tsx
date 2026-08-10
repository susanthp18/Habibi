import { FileText, Mail, MessageCircle, PhoneCall } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Channel, Customer, DocStatus } from "@/data/customer360-seed";
import { fmtDate } from "@/data/customer360-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const STATUS_TONE: Record<DocStatus, LozengeTone> = {
  requested: "neutral",
  generating: "warning",
  sent: "success",
  failed: "danger",
};

const CHANNEL_ICON: Partial<Record<Channel, React.ComponentType<{ className?: string }>>> = {
  voice: PhoneCall,
  whatsapp: MessageCircle,
  chat: MessageCircle,
  email: Mail,
};

export function DocumentsTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  return (
    <div className="space-y-200">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-text">Document fulfillment</div>
          <div className="text-xs text-text-subtle">Bot captures the request, back-office (or bot) sends the file.</div>
        </div>
        <Button onClick={onCreate}>
          <FileText className="h-3.5 w-3.5" />
          Send statement
        </Button>
      </div>

      {customer.documents.length === 0 ? (
        <div className="rounded-large border border-dashed border-border bg-surface p-500 text-center text-sm text-text-subtlest">
          No documents requested yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-large border border-border bg-surface">
          <table className="w-full text-sm">
            <thead className="bg-surface-sunken text-body-small text-text-subtle">
              <tr>
                <th className="px-200 py-100 text-left font-medium">Type</th>
                <th className="px-200 py-100 text-left font-medium">Requested via</th>
                <th className="px-200 py-100 text-left font-medium">Requested on</th>
                <th className="px-200 py-100 text-left font-medium">Delivered via</th>
                <th className="px-200 py-100 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {customer.documents.map((d) => {
                const InIcon = CHANNEL_ICON[d.requestedVia] ?? MessageCircle;
                const OutIcon = d.deliveryChannel === "email" ? Mail : MessageCircle;
                return (
                  <tr key={d.id} className="border-t border-border hover:bg-background-brand-subtlest/30">
                    <td className="px-200 py-150 text-sm text-text">{d.type}</td>
                    <td className="px-200 py-150 text-xs text-text-subtle">
                      <span className="inline-flex items-center gap-050 capitalize">
                        <InIcon className="h-3 w-3" /> {d.requestedVia}
                      </span>
                    </td>
                    <td className="px-200 py-150 text-xs text-text-subtle tabular">{fmtDate(d.requestedAt)}</td>
                    <td className="px-200 py-150 text-xs text-text-subtle">
                      <span className="inline-flex items-center gap-050 capitalize">
                        <OutIcon className="h-3 w-3" /> {d.deliveryChannel}
                      </span>
                    </td>
                    <td className="px-200 py-150">
                      <Lozenge tone={STATUS_TONE[d.status]}>{d.status}</Lozenge>
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
