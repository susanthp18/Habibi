import { useMemo } from "react";
import { FileText, Mail, MessageCircle, PhoneCall } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Channel, Customer, DocStatus, DocumentRequest } from "@/data/customer360-seed";
import { fmtDate } from "@/data/customer360-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import {
  FilterTable,
  type FilterChip,
  type FilterTableColumn,
} from "@/components/records/FilterTable";

const STATUS_TONE: Record<DocStatus, LozengeTone> = {
  requested: "neutral",
  generating: "warning",
  sent: "success",
  failed: "danger",
};

const STATUS_DOT: Record<DocStatus, string> = {
  requested: "var(--icon-accent-gray)",
  generating: "var(--icon-accent-yellow)",
  sent: "var(--icon-accent-green)",
  failed: "var(--icon-accent-red)",
};

const STATUS_ORDER: DocStatus[] = ["requested", "generating", "sent", "failed"];

const CHANNEL_ICON: Partial<Record<Channel, React.ComponentType<{ className?: string }>>> = {
  voice: PhoneCall,
  whatsapp: MessageCircle,
  chat: MessageCircle,
  email: Mail,
};

export function DocumentsTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  const chips = useMemo<FilterChip<DocStatus>[]>(() => {
    const counts = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<DocStatus, number>;
    for (const d of customer.documents) counts[d.status] += 1;
    return [
      { key: "all", label: "All", count: customer.documents.length },
      ...STATUS_ORDER.map((s) => ({
        key: s,
        label: s.charAt(0).toUpperCase() + s.slice(1),
        dot: STATUS_DOT[s],
        count: counts[s],
      })),
    ];
  }, [customer.documents]);

  const columns = useMemo<FilterTableColumn<DocumentRequest>[]>(
    () => [
      {
        id: "type",
        header: "Type",
        width: "1.4fr",
        cell: (d) => <span className="truncate text-body text-text">{d.type}</span>,
      },
      {
        id: "requestedVia",
        header: "Requested via",
        width: "1fr",
        cell: (d) => {
          const InIcon = CHANNEL_ICON[d.requestedVia] ?? MessageCircle;
          return (
            <span className="inline-flex items-center gap-050 capitalize text-body-small text-text-subtle">
              <InIcon className="h-3 w-3" /> {d.requestedVia}
              {d.source && d.source !== "crm" ? ` · ${d.source}` : ""}
            </span>
          );
        },
      },
      {
        id: "requestedAt",
        header: "Requested on",
        width: "0.9fr",
        cell: (d) => (
          <span className="text-body-small tabular-nums text-text-subtle">
            {fmtDate(d.requestedAt)}
          </span>
        ),
      },
      {
        id: "delivered",
        header: "Delivered via",
        width: "1fr",
        cell: (d) => {
          const OutIcon = d.deliveryChannel === "email" ? Mail : MessageCircle;
          return (
            <span className="inline-flex items-center gap-050 capitalize text-body-small text-text-subtle">
              <OutIcon className="h-3 w-3" /> {d.deliveryChannel}
            </span>
          );
        },
      },
      {
        id: "status",
        header: "Status",
        width: "0.8fr",
        cell: (d) => <Lozenge tone={STATUS_TONE[d.status]}>{d.status}</Lozenge>,
      },
    ],
    [],
  );

  return (
    <div className="space-y-200">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-text">Document fulfillment</div>
          <div className="text-xs text-text-subtle">
            Bot captures the request, back-office (or bot) sends the file.
          </div>
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
        <FilterTable
          rows={customer.documents}
          getRowId={(d) => d.id}
          getStatus={(d) => d.status}
          chips={chips}
          columns={columns}
          emptyMessage="No documents match this filter."
          ariaLabel="Customer document requests"
        />
      )}
    </div>
  );
}
