import { LayoutGrid, Rows } from "lucide-react";
import { ViewToggle as Toggle } from "@/components/ui/view-toggle";

export type UpsellView = "board" | "table";

const OPTIONS = [
  { id: "board" as const, label: "Pipeline", icon: LayoutGrid },
  { id: "table" as const, label: "Table", icon: Rows },
];

export function ViewToggle({
  view,
  onChange,
}: {
  view: UpsellView;
  onChange: (v: UpsellView) => void;
}) {
  return <Toggle view={view} onChange={onChange} options={OPTIONS} />;
}
