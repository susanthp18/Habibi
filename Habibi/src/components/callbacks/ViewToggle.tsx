import { CalendarDays, List, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

export type CbView = "week" | "list" | "missed";

export function ViewToggle({ view, onChange, missedCount }: { view: CbView; onChange: (v: CbView) => void; missedCount: number }) {
  const items: { id: CbView; label: string; icon: typeof CalendarDays; badge?: number }[] = [
    { id: "week", label: "Week calendar", icon: CalendarDays },
    { id: "list", label: "List", icon: List },
    { id: "missed", label: "Missed", icon: AlertTriangle, badge: missedCount },
  ];
  return (
    <div className="inline-flex shrink-0 rounded-md border border-[var(--border-token)] bg-surface-card p-0.5">
      {items.map((it) => {
        const Icon = it.icon;
        const active = view === it.id;
        return (
          <button
            key={it.id}
            onClick={() => onChange(it.id)}
            className={cn(
              "flex items-center gap-1.5 rounded px-2.5 py-1 text-[12px]",
              active
                ? "bg-brand-tint text-brand-primary-dark font-semibold"
                : "text-text-secondary hover:bg-surface-sunken",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {it.label}
            {typeof it.badge === "number" && it.badge > 0 && (
              <span className={cn("rounded-full px-1.5 text-[10px] font-semibold", active ? "bg-red-100 text-red-700" : "bg-red-100 text-red-700")}>
                {it.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
