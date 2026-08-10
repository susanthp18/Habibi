import { CalendarDays, List, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export type CbView = "week" | "list" | "missed";

export function ViewToggle({ view, onChange, missedCount }: { view: CbView; onChange: (v: CbView) => void; missedCount: number }) {
  const items: { id: CbView; label: string; icon: typeof CalendarDays; badge?: number }[] = [
    { id: "week", label: "Week calendar", icon: CalendarDays },
    { id: "list", label: "List", icon: List },
    { id: "missed", label: "Missed", icon: AlertTriangle, badge: missedCount },
  ];
  return (
    <div className="inline-flex shrink-0 rounded-medium border border-border bg-surface p-025">
      {items.map((it) => {
        const Icon = it.icon;
        const active = view === it.id;
        return (
          <button
            key={it.id}
            onClick={() => onChange(it.id)}
            className={cn(
              "flex items-center gap-075 rounded px-150 py-050 text-body-small",
              active
                ? "bg-background-brand-subtlest text-text-brand font-semibold"
                : "text-text-subtle hover:bg-surface-sunken",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {it.label}
            {typeof it.badge === "number" && it.badge > 0 && (
              <Badge variant="destructive">{it.badge}</Badge>
            )}
          </button>
        );
      })}
    </div>
  );
}
