import { cn } from "@/lib/utils";
import { STATUS_LABELS, STATUS_ORDER, type DocStatus } from "@/data/documents-seed";
import { ChevronRight } from "lucide-react";

const TONE: Record<DocStatus, { bar: string; text: string; dot: string }> = {
  requested: { bar: "bg-background-brand-subtlest", text: "text-text-brand", dot: "bg-background-brand-bold" },
  generating: { bar: "bg-background-warning-subtler", text: "text-text-warning-bolder", dot: "bg-background-warning-bold" },
  sent: { bar: "bg-background-success-subtler", text: "text-text-success-bolder", dot: "bg-background-success-bold" },
  failed: { bar: "bg-background-danger-subtler", text: "text-text-danger-bolder", dot: "bg-background-danger-bold" },
};

interface Props {
  counts: Record<DocStatus, number>;
  active: DocStatus[]; // status filter
  onToggle: (s: DocStatus) => void;
}

export function PipelineStrip({ counts, active, onToggle }: Props) {
  return (
    <div className="shrink-0 rounded-large border border-border bg-surface p-075">
      <div className="flex items-stretch gap-050">
        {STATUS_ORDER.map((s, i) => {
          const on = active.includes(s) || active.length === 0;
          const tone = TONE[s];
          return (
            <div key={s} className="flex flex-1 items-stretch gap-050">
              <button
                onClick={() => onToggle(s)}
                className={cn(
                  "flex flex-1 items-center justify-between gap-100 rounded-medium px-150 py-075 text-left transition-all",
                  on ? tone.bar : "bg-transparent hover:bg-surface-sunken",
                  !on && "opacity-60",
                )}
              >
                <div className="flex items-center gap-075">
                  <span className={cn("h-100 w-100 rounded-full", tone.dot)} />
                  <span className={cn("text-body-small font-semibold", on ? tone.text : "text-text-subtle")}>
                    {STATUS_LABELS[s]}
                  </span>
                </div>
                <span className={cn("text-body font-semibold tabular-nums", on ? tone.text : "text-text-subtlest")}>
                  {counts[s]}
                </span>
              </button>
              {i < STATUS_ORDER.length - 1 && (
                <ChevronRight className="my-auto h-3.5 w-3.5 shrink-0 text-text-subtlest" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
