import { CheckCircle2, Circle, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ComplianceItem } from "@/data/handoff-seed";

type Props = {
  items: ComplianceItem[];
  checked: Record<string, boolean>;
  onToggle: (id: string) => void;
};

export function ComplianceChecklist({ items, checked, onToggle }: Props) {
  const total = items.filter((i) => i.required).length;
  const done = items.filter((i) => i.required && checked[i.id]).length;
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-brand-navy">
          <ShieldCheck className="h-3.5 w-3.5 text-success" />
          Compliance
        </div>
        <span className="tabular text-[11px] text-text-secondary">
          {done}/{total} required
        </span>
      </div>
      <div className="px-3 pt-2">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div
            className="h-full rounded-full bg-success transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <ul className="px-1 py-1">
        {items.map((item) => {
          const isDone = !!checked[item.id];
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onToggle(item.id)}
                className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-sunken"
              >
                {isDone ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                ) : (
                  <Circle className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" />
                )}
                <span
                  className={cn(
                    "text-[12px]",
                    isDone ? "text-text-secondary line-through" : "text-text-primary",
                  )}
                >
                  {item.label}
                  {!item.required && (
                    <span className="ml-1 text-[10px] text-text-muted">(optional)</span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
