import { cn } from "@/lib/utils";
import { STATUS_LABELS, STATUS_ORDER, type DocStatus } from "@/data/documents-seed";
import { ChevronRight } from "lucide-react";

const TONE: Record<DocStatus, { bar: string; text: string; dot: string }> = {
  requested: { bar: "bg-brand-tint", text: "text-brand-primary-dark", dot: "bg-brand-primary" },
  generating: { bar: "bg-amber-100", text: "text-amber-800", dot: "bg-amber-500" },
  sent: { bar: "bg-emerald-100", text: "text-emerald-800", dot: "bg-emerald-500" },
  failed: { bar: "bg-red-100", text: "text-red-700", dot: "bg-red-500" },
};

interface Props {
  counts: Record<DocStatus, number>;
  active: DocStatus[]; // status filter
  onToggle: (s: DocStatus) => void;
}

export function PipelineStrip({ counts, active, onToggle }: Props) {
  return (
    <div className="shrink-0 rounded-lg border border-[var(--border-token)] bg-surface-card p-1.5">
      <div className="flex items-stretch gap-1">
        {STATUS_ORDER.map((s, i) => {
          const on = active.includes(s) || active.length === 0;
          const tone = TONE[s];
          return (
            <div key={s} className="flex flex-1 items-stretch gap-1">
              <button
                onClick={() => onToggle(s)}
                className={cn(
                  "flex flex-1 items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left transition-all",
                  on ? tone.bar : "bg-transparent hover:bg-surface-sunken",
                  !on && "opacity-60",
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span className={cn("h-2 w-2 rounded-full", tone.dot)} />
                  <span className={cn("text-[11.5px] font-semibold", on ? tone.text : "text-text-secondary")}>
                    {STATUS_LABELS[s]}
                  </span>
                </div>
                <span className={cn("text-[13px] font-semibold tabular-nums", on ? tone.text : "text-text-muted")}>
                  {counts[s]}
                </span>
              </button>
              {i < STATUS_ORDER.length - 1 && (
                <ChevronRight className="my-auto h-3.5 w-3.5 shrink-0 text-text-muted" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
