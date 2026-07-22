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
        "inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-[12px] transition-colors",
        view === v ? "bg-brand-primary text-white" : "text-text-secondary hover:bg-surface-sunken",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
  return (
    <div className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card p-0.5">
      {item("board", "Pipeline", LayoutGrid)}
      {item("table", "Table", Rows)}
    </div>
  );
}
