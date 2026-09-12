import { CalendarDays, List, AlertTriangle } from "lucide-react";
import { ViewToggle as Toggle } from "@/components/ui/view-toggle";

export type CbView = "week" | "list" | "missed";

export function ViewToggle({
  view,
  onChange,
  missedCount,
}: {
  view: CbView;
  onChange: (v: CbView) => void;
  missedCount: number;
}) {
  return (
    <Toggle
      view={view}
      onChange={onChange}
      options={[
        { id: "week", label: "Week calendar", icon: CalendarDays },
        { id: "list", label: "List", icon: List },
        { id: "missed", label: "Missed", icon: AlertTriangle, count: missedCount },
      ]}
    />
  );
}
