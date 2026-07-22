import { AlertOctagon, Timer } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Customer, Dispute, DisputeStatus } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { TYPE_LABELS, type DisputeType } from "@/data/disputes-seed";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<DisputeStatus, string> = {
  new: "New",
  under_review: "Under review",
  awaiting_customer: "Awaiting customer",
  resolved: "Resolved",
  rejected: "Rejected",
};

const STATUS_TONE: Record<DisputeStatus, string> = {
  new: "bg-brand-tint text-brand-primary-dark",
  under_review: "bg-warning-bg text-warning",
  awaiting_customer: "bg-surface-sunken text-text-secondary",
  resolved: "bg-success-bg text-success",
  rejected: "bg-danger-bg text-danger",
};

export function DisputesTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-brand-navy">{customer.disputes.length} disputes on file</div>
          <div className="text-xs text-text-secondary">Bot flags, human resolves. SLA counts down from filing time.</div>
        </div>
        <Button onClick={onCreate}>
          <AlertOctagon className="h-3.5 w-3.5" />
          Raise dispute
        </Button>
      </div>

      {customer.disputes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-surface-card p-10 text-center text-sm text-text-muted">
          No disputes for this customer. Clean record.
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {customer.disputes.map((d) => (
            <DisputeCard key={d.id} d={d} />
          ))}
        </div>
      )}
    </div>
  );
}

function DisputeCard({ d }: { d: Dispute }) {
  return (
    <div className="rounded-lg border border-border bg-surface-card p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="text-xs font-semibold text-text-muted tabular">{d.id}</div>
          {/* Backend stores the canonical enum; render the human label. */}
          <div className="text-sm font-medium text-brand-navy">
            {TYPE_LABELS[d.type as DisputeType] ?? d.type}
          </div>
        </div>
        <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase", STATUS_TONE[d.status])}>
          {STATUS_LABEL[d.status]}
        </span>
      </div>
      <blockquote className="mt-2 rounded-md border-l-2 border-brand-primary/40 bg-surface-sunken px-3 py-2 text-xs italic text-text-secondary">
        {d.transcriptSnippet}
      </blockquote>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px] text-text-secondary">
        <div>
          <div className="text-[10px] uppercase text-text-muted">Amount</div>
          <div className="text-sm font-semibold text-brand-navy tabular">{fmtMoney(d.amount)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-text-muted">Filed</div>
          <div className="text-sm text-text-primary tabular">{fmtDate(d.filedAt)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-text-muted">Assignee</div>
          <div className="text-sm text-text-primary">{d.assignee ?? "Unassigned"}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[11px]">
        <span className="inline-flex items-center gap-1 text-warning">
          <Timer className="h-3 w-3" />
          {d.slaLabel}
        </span>
        <button className="font-medium text-brand-primary hover:underline">View in Disputes Queue →</button>
      </div>
    </div>
  );
}
