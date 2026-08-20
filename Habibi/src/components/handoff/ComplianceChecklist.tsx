import { CheckCircle2, Circle, Lock, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ComplianceItem } from "@/api/handoff";

type Props = {
  items: ComplianceItem[];
  checked: Record<string, boolean>;
  onToggle: (id: string) => void;
};

export function ComplianceChecklist({ items, checked, onToggle }: Props) {
  const total = items.filter((i) => i.required).length;
  const done = items.filter((i) => i.required && (checked[i.id] || i.checked)).length;
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <ShieldCheck className="h-3.5 w-3.5 text-text-success" />
          Compliance
        </div>
        <span className="tabular text-body-small text-text-subtle">
          {done}/{total} required
        </span>
      </div>
      <div className="px-150 pt-100">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div
            className="h-full rounded-full bg-background-success transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <ul className="px-050 py-050">
        {items.map((item) => {
          const isDone = !!(checked[item.id] || item.checked);
          const locked = !!item.locked;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => !locked && onToggle(item.id)}
                disabled={locked}
                className="flex w-full items-start gap-100 rounded-medium px-100 py-075 text-left hover:bg-surface-sunken disabled:cursor-not-allowed disabled:hover:bg-transparent"
              >
                {isDone ? (
                  <CheckCircle2 className="mt-025 h-4 w-4 shrink-0 text-text-success" />
                ) : locked ? (
                  <Lock className="mt-025 h-4 w-4 shrink-0 text-text-subtlest" />
                ) : (
                  <Circle className="mt-025 h-4 w-4 shrink-0 text-text-subtlest" />
                )}
                <span
                  className={cn(
                    "text-body-small",
                    isDone ? "text-text-subtle line-through" : "text-text",
                  )}
                >
                  {item.label}
                  {!item.required && (
                    <span className="ml-050 text-body-small text-text-subtlest">(optional)</span>
                  )}
                  {locked && (
                    <span className="ml-050 text-body-small text-text-subtlest">(system)</span>
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
