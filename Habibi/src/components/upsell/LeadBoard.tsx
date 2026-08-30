import { useState } from "react";
import {
  fmtMoney,
  leadValue,
  STAGE_LABELS,
  STAGE_ORDER,
  type Lead,
  type LeadStage,
} from "@/data/upsell-seed";
import { cn } from "@/lib/utils";
import { LeadCard } from "./LeadCard";

interface Props {
  leads: Lead[];
  onOpen: (l: Lead) => void;
  onDropStage: (id: string, stage: LeadStage) => void;
}

const columnAccent: Record<LeadStage, string> = {
  interested: "border-t-border-brand",
  contacted: "border-t-indigo-500",
  qualified: "border-t-amber-500",
  won: "border-t-emerald-500",
  lost: "border-t-slate-400",
};

export function LeadBoard({ leads, onOpen, onDropStage }: Props) {
  const [dragOver, setDragOver] = useState<LeadStage | null>(null);

  return (
    <div className="flex min-h-0 flex-1 gap-150 overflow-x-auto pb-100">
      {STAGE_ORDER.map((stage) => {
        const items = leads
          .filter((l) => l.stage === stage)
          .sort((a, b) => {
            if (stage === "won" || stage === "lost") {
              return (
                new Date(b.closedAt ?? b.capturedAt).getTime() -
                new Date(a.closedAt ?? a.capturedAt).getTime()
              );
            }
            const pri = { high: 0, normal: 1, low: 2 } as const;
            if (pri[a.priority] !== pri[b.priority]) return pri[a.priority] - pri[b.priority];
            const af = a.nextFollowUpAt ? new Date(a.nextFollowUpAt).getTime() : Infinity;
            const bf = b.nextFollowUpAt ? new Date(b.nextFollowUpAt).getTime() : Infinity;
            return af - bf;
          });
        const subtotal = items.reduce((s, l) => s + leadValue(l), 0);
        return (
          <div
            key={stage}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              setDragOver(stage);
            }}
            onDragLeave={() => setDragOver((s) => (s === stage ? null : s))}
            onDrop={(e) => {
              e.preventDefault();
              const id = e.dataTransfer.getData("text/plain");
              if (id) onDropStage(id, stage);
              setDragOver(null);
            }}
            className={cn(
              "flex w-[18.75rem] shrink-0 flex-col rounded-large border border-t-2 bg-surface-sunken/60 transition-colors",
              columnAccent[stage],
              dragOver === stage
                ? "bg-background-brand-subtlest/40 ring-2 ring-border-brand/40"
                : "border-border",
            )}
          >
            <div className="flex items-center justify-between border-b border-border px-150 py-100">
              <div>
                <div className="text-body-small font-semibold text-text">{STAGE_LABELS[stage]}</div>
                <div className="text-body-small text-text-subtlest tabular-nums">
                  {items.length} · {fmtMoney(subtotal)}
                </div>
              </div>
            </div>
            <div className="flex-1 space-y-100 overflow-y-auto p-100">
              {items.length === 0 ? (
                <div className="rounded border border-dashed border-border p-200 text-center text-body-small text-text-subtlest">
                  Drop here
                </div>
              ) : (
                items.map((l) => <LeadCard key={l.id} lead={l} onOpen={onOpen} />)
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
