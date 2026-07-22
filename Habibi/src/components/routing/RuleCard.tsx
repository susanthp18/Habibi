import { GripVertical, MoreVertical, Copy, Trash2, Pencil } from "lucide-react";
import type { Rule } from "@/data/routing-seed";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { RuleChips } from "./RuleChips";
import { cn } from "@/lib/utils";

type Props = {
  rule: Rule;
  priority: number;
  selected: boolean;
  onSelect: () => void;
  onToggle: (v: boolean) => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onDragStart: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: () => void;
};

const CATEGORY_STYLE: Record<string, string> = {
  Escalation: "bg-red-50 text-red-700 border-red-200",
  Handoff: "bg-amber-50 text-amber-700 border-amber-200",
  Throttle: "bg-blue-50 text-blue-700 border-blue-200",
  Compliance: "bg-violet-50 text-violet-700 border-violet-200",
  Routing: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

export function RuleCard({
  rule, priority, selected, onSelect, onToggle, onEdit, onDuplicate, onDelete,
  onDragStart, onDragOver, onDrop,
}: Props) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onClick={onSelect}
      className={cn(
        "group rounded-lg border bg-surface-card p-3 transition-all cursor-pointer",
        selected ? "border-brand-primary ring-1 ring-brand-primary/30" : "border-[var(--border-token)] hover:border-brand-primary/40",
        !rule.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start gap-2">
        <div className="flex flex-col items-center gap-1 pt-0.5">
          <GripVertical className="h-4 w-4 cursor-grab text-text-muted" />
          <span className="rounded-md bg-brand-navy px-1.5 py-0.5 text-[10px] font-semibold text-white">
            #{priority}
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="truncate text-[13px] font-semibold text-brand-navy">{rule.name}</div>
            <span className={cn("rounded-full border px-1.5 py-0.5 text-[10px] font-medium", CATEGORY_STYLE[rule.category])}>
              {rule.category}
            </span>
          </div>
          {rule.description && (
            <div className="mt-0.5 text-[11px] text-text-secondary">{rule.description}</div>
          )}
          <div className="mt-2">
            <RuleChips rule={rule} />
          </div>
        </div>

        <div className="flex flex-col items-end gap-2" onClick={e => e.stopPropagation()}>
          <div className="text-[10px] text-text-muted">{rule.triggersLast24h} triggers · 24h</div>
          <div className="flex items-center gap-1">
            <Switch checked={rule.enabled} onCheckedChange={onToggle} />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={onEdit}><Pencil className="mr-2 h-4 w-4" />Edit</DropdownMenuItem>
                <DropdownMenuItem onClick={onDuplicate}><Copy className="mr-2 h-4 w-4" />Duplicate</DropdownMenuItem>
                <DropdownMenuItem onClick={onDelete} className="text-red-600 focus:text-red-700"><Trash2 className="mr-2 h-4 w-4" />Delete</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
    </div>
  );
}
