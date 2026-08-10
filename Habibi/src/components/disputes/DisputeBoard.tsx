import { useState } from "react";
import {
  STATUS_LABELS,
  STATUS_ORDER,
  fmtMoney,
  slaInfo,
  type Dispute,
  type DisputeStatus,
} from "@/data/disputes-seed";
import { cn } from "@/lib/utils";
import { DisputeCard } from "./DisputeCard";

interface Props {
  disputes: Dispute[];
  counts: Record<DisputeStatus, number>;
  subtotals: Record<DisputeStatus, number>;
  onOpen: (d: Dispute) => void;
  onAssignMe: (d: Dispute) => void;
  onDropStatus: (id: string, status: DisputeStatus) => void;
}

const columnAccent: Record<DisputeStatus, string> = {
  new: "border-t-border-brand",
  under_review: "border-t-border-warning",
  awaiting_customer: "border-t-border-discovery",
  resolved: "border-t-border-success",
  rejected: "border-t-border-bold",
};

export function DisputeBoard({ disputes, counts, subtotals, onOpen, onAssignMe, onDropStatus }: Props) {
  const [dragOver, setDragOver] = useState<DisputeStatus | null>(null);

  return (
    <div className="flex min-h-0 flex-1 gap-150 overflow-x-auto pb-100">
      {STATUS_ORDER.map((status) => {
        // Sort: breached first, then by SLA remaining, then capture time desc
        const items = disputes
          .filter((d) => d.status === status)
          .sort((a, b) => {
            const sa = slaInfo(a);
            const sb = slaInfo(b);
            if (sa.tone === "breach" && sb.tone !== "breach") return -1;
            if (sb.tone === "breach" && sa.tone !== "breach") return 1;
            return sa.msRemaining - sb.msRemaining;
          });
        return (
          <div
            key={status}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              setDragOver(status);
            }}
            onDragLeave={() => setDragOver((s) => (s === status ? null : s))}
            onDrop={(e) => {
              e.preventDefault();
              const id = e.dataTransfer.getData("text/plain");
              if (id) onDropStatus(id, status);
              setDragOver(null);
            }}
            className={cn(
              "flex w-[18.75rem] shrink-0 flex-col rounded-large border border-t-2 bg-surface-sunken/60 transition-colors",
              columnAccent[status],
              dragOver === status ? "bg-background-brand-subtlest/40 ring-2 ring-border-brand/40" : "border-border",
            )}
          >
            <div className="flex items-center justify-between border-b border-border px-150 py-100">
              <div>
                <div className="text-body-small font-semibold text-text">{STATUS_LABELS[status]}</div>
                <div className="text-body-small text-text-subtlest tabular-nums">
                  {counts[status]} · {fmtMoney(subtotals[status])}
                </div>
              </div>
            </div>
            <div className="flex-1 space-y-100 overflow-y-auto p-100">
              {items.length === 0 ? (
                <div className="rounded border border-dashed border-border p-200 text-center text-body-small text-text-subtlest">
                  No disputes
                </div>
              ) : (
                items.map((d) => (
                  <DisputeCard key={d.id} dispute={d} onOpen={onOpen} onAssignMe={onAssignMe} />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
