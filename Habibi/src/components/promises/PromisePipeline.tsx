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
  upcoming: "border-t-border-brand",
  due_today: "border-t-amber-500",
  kept: "border-t-emerald-500",
  broken: "border-t-red-500",
  partial: "border-t-orange-500",
};

export function PromisePipeline({ promises, counts, subtotals, onOpen, onMark, onDropStatus }: Props) {
  const [dragOver, setDragOver] = useState<PromiseStatus | null>(null);

  return (
    <div className="flex gap-150 overflow-x-auto pb-100">
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
              "flex w-[17.5rem] shrink-0 flex-col rounded-large border border-t-2 bg-surface-sunken/60 transition-colors",
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
