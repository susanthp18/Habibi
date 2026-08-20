import { GripVertical, MoreVertical, Copy, Trash2, Pencil } from "lucide-react";
import type { Rule } from "@/data/routing-seed";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { RuleChips } from "./RuleChips";
import { cn } from "@/lib/utils";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

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

const CATEGORY_STYLE: Record<string, LozengeTone> = {
  Escalation: "danger",
  Handoff: "warning",
  Throttle: "information",
  Compliance: "discovery",
  Routing: "success",
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
        "group rounded-large border bg-surface p-150 transition-all cursor-pointer",
        selected ? "border-border-brand ring-1 ring-border-brand/30" : "border-border hover:border-border-brand/40",
        !rule.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start gap-100">
        <div className="flex flex-col items-center gap-050 pt-025">
          <GripVertical className="h-4 w-4 cursor-grab text-text-subtlest" />
          <span className="rounded-medium bg-background-brand-boldest px-075 py-025 text-body-small font-semibold text-white">
            #{priority}
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-100">
            <div className="truncate text-body font-semibold text-text">{rule.name}</div>
            <Lozenge tone={CATEGORY_STYLE[rule.category]}>
              {rule.category}
            </Lozenge>
          </div>
          {rule.description && (
            <div className="mt-025 text-body-small text-text-subtle">{rule.description}</div>
          )}
          <div className="mt-100">
            <RuleChips rule={rule} />
          </div>
        </div>

        <div className="flex flex-col items-end gap-100" onClick={e => e.stopPropagation()}>
          <div className="text-body-small text-text-subtlest">{rule.triggersLast24h} triggers · 24h</div>
          <div className="flex items-center gap-050">
            <Switch
              aria-label={`Enable rule ${rule.name}`}
              checked={rule.enabled}
              onCheckedChange={onToggle}
            />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={onEdit}><Pencil className="mr-100 h-4 w-4" />Edit</DropdownMenuItem>
                <DropdownMenuItem onClick={onDuplicate}><Copy className="mr-100 h-4 w-4" />Duplicate</DropdownMenuItem>
                <DropdownMenuItem onClick={onDelete} className="text-text-danger focus:text-text-danger-bolder"><Trash2 className="mr-100 h-4 w-4" />Delete</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
    </div>
  );
}
