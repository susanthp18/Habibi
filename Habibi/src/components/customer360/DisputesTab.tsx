import { Timer } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Customer, Dispute, DisputeStatus } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { TYPE_LABELS, type DisputeType } from "@/data/disputes-seed";
import { StatusChip, disputeStatusTone } from "./StatusChip";

const STATUS_LABEL: Record<DisputeStatus, string> = {
  new: "New",
  under_review: "Under review",
  awaiting_customer: "Awaiting customer",
  resolved: "Resolved",
  rejected: "Rejected",
};

export function DisputesTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  return (
    <div className="space-y-200">
      <div className="flex items-center justify-between gap-150">
        <div>
          <div className="text-sm font-semibold text-text">{customer.disputes.length} disputes on file</div>
          <div className="text-xs text-text-subtle">Bot flags, human resolves. SLA counts down from filing time.</div>
        </div>
        {customer.disputes.length === 0 ? (
          <Button size="sm" className="bg-background-brand-bold hover:bg-background-brand-bold-hovered" onClick={onCreate}>
            Raise dispute
          </Button>
        ) : null}
      </div>

      {customer.disputes.length === 0 ? (
        <div className="rounded-large border border-dashed border-border bg-surface p-500 text-center text-sm text-text-subtlest">
          No disputes for this customer. Clean record.
        </div>
      ) : (
        <div className="grid gap-150 md:grid-cols-2">
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
    <div className="rounded-large border border-border bg-surface p-200">
      <div className="mb-100 flex items-start justify-between gap-100">
        <div>
          <div className="text-xs font-semibold text-text-subtlest tabular">{d.id}</div>
          <div className="text-sm font-medium text-text">
            {TYPE_LABELS[d.type as DisputeType] ?? d.type}
          </div>
        </div>
        <StatusChip label={STATUS_LABEL[d.status]} tone={disputeStatusTone(d.status)} />
      </div>
      <blockquote className="mt-100 rounded-medium border-l-2 border-border-brand/40 bg-surface-sunken px-150 py-100 text-xs italic text-text-subtle">
        {d.transcriptSnippet}
      </blockquote>
      <div className="mt-150 grid grid-cols-3 gap-100 text-body-small text-text-subtle">
        <div>
          <div className="text-body-small text-text-subtlest">Amount</div>
          <div className="text-sm font-semibold text-text tabular">{fmtMoney(d.amount)}</div>
        </div>
        <div>
          <div className="text-body-small text-text-subtlest">Filed</div>
          <div className="text-sm text-text tabular">{fmtDate(d.filedAt)}</div>
        </div>
        <div>
          <div className="text-body-small text-text-subtlest">Assignee</div>
          <div className="text-sm text-text">{d.assignee ?? "Unassigned"}</div>
        </div>
      </div>
      <div className="mt-150 flex items-center justify-between border-t border-border pt-150 text-body-small">
        <span className="inline-flex items-center gap-050 text-text-warning">
          <Timer className="h-3 w-3" />
          {d.slaLabel}
        </span>
        <button className="font-medium text-text-brand hover:underline">View in Disputes Queue →</button>
      </div>
    </div>
  );
}
