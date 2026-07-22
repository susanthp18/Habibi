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
  new: "border-t-brand-primary",
  under_review: "border-t-amber-500",
  awaiting_customer: "border-t-violet-500",
  resolved: "border-t-emerald-500",
  rejected: "border-t-slate-400",
};

export function DisputeBoard({ disputes, counts, subtotals, onOpen, onAssignMe, onDropStatus }: Props) {
  const [dragOver, setDragOver] = useState<DisputeStatus | null>(null);

  return (
    <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
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
              "flex w-[300px] shrink-0 flex-col rounded-lg border border-t-2 bg-surface-sunken/60 transition-colors",
              columnAccent[status],
              dragOver === status ? "bg-brand-tint/40 ring-2 ring-brand-primary/40" : "border-[var(--border-token)]",
            )}
          >
            <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
              <div>
                <div className="text-[12px] font-semibold text-brand-navy">{STATUS_LABELS[status]}</div>
                <div className="text-[10.5px] text-text-muted tabular-nums">
                  {counts[status]} · {fmtMoney(subtotals[status])}
                </div>
              </div>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto p-2">
              {items.length === 0 ? (
                <div className="rounded border border-dashed border-[var(--border-token)] p-4 text-center text-[11px] text-text-muted">
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
