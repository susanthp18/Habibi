import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ViewOption<V extends string> {
  id: V;
  label: string;
  icon: LucideIcon;
  /** A count worth showing beside the label, e.g. missed callbacks. */
  count?: number;
}

/** A segmented switch between the views of one list. */
export function ViewToggle<V extends string>({
  view,
  onChange,
  options,
  className,
}: {
  view: V;
  onChange: (v: V) => void;
  options: ViewOption<V>[];
  className?: string;
}) {
  return (
    <div
      role="group"
      className={cn(
        "inline-flex shrink-0 items-center gap-050 rounded-medium border border-border bg-surface p-025",
        className,
      )}
    >
      {options.map(({ id, label, icon: Icon, count }) => (
        <button
          key={id}
          type="button"
          aria-pressed={view === id}
          onClick={() => onChange(id)}
          className={cn(
            "inline-flex items-center gap-075 rounded px-150 py-050 text-body-small transition-colors",
            view === id
              ? "bg-background-brand-subtlest font-semibold text-text-brand"
              : "text-text-subtle hover:bg-surface-sunken",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
          {count != null && count > 0 && (
            <span className="rounded-full bg-background-danger-bold px-075 text-body-micro font-semibold text-white">
              {count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
