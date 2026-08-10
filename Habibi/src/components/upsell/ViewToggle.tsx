import { LayoutGrid, Rows } from "lucide-react";
import { cn } from "@/lib/utils";

export type UpsellView = "board" | "table";

interface Props {
  view: UpsellView;
  onChange: (v: UpsellView) => void;
}

export function ViewToggle({ view, onChange }: Props) {
  const item = (v: UpsellView, label: string, Icon: React.ComponentType<{ className?: string }>) => (
    <button
      key={v}
      onClick={() => onChange(v)}
      className={cn(
        "inline-flex items-center gap-075 rounded px-150 py-050 text-body-small transition-colors",
        view === v ? "bg-background-brand-bold text-white" : "text-text-subtle hover:bg-surface-sunken",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
  return (
    <div className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface p-025">
      {item("board", "Pipeline", LayoutGrid)}
      {item("table", "Table", Rows)}
    </div>
  );
}
