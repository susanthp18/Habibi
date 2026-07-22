import { useState } from "react";
import { PromiseCard } from "./PromiseCard";
import { STATUS_LABELS, STATUS_ORDER, fmtMoney, type Promise, type PromiseStatus } from "@/data/promises-seed";
import { cn } from "@/lib/utils";

interface Props {
  promises: Promise[];
  counts: Record<PromiseStatus, number>;
  subtotals: Record<PromiseStatus, number>;
  onOpen: (p: Promise) => void;
  onMark: (p: Promise, status: PromiseStatus) => void;
  onDropStatus: (promiseId: string, status: PromiseStatus) => void;
}

const columnAccent: Record<PromiseStatus, string> = {
  upcoming: "border-t-brand-primary",
  due_today: "border-t-amber-500",
  kept: "border-t-emerald-500",
  broken: "border-t-red-500",
  partial: "border-t-orange-500",
};

export function PromisePipeline({ promises, counts, subtotals, onOpen, onMark, onDropStatus }: Props) {
  const [dragOver, setDragOver] = useState<PromiseStatus | null>(null);

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {STATUS_ORDER.map((status) => {
        const items = promises.filter((p) => p.status === status);
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
              "flex w-[280px] shrink-0 flex-col rounded-lg border border-t-2 bg-surface-sunken/60 transition-colors",
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
                  No promises
                </div>
              ) : (
                items.map((p) => (
                  <PromiseCard key={p.id} promise={p} onOpen={onOpen} onMark={onMark} />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
