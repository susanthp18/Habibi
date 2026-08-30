import { useState } from "react";
import type { Rule, RuleCategory } from "@/data/routing-seed";
import { RuleCard } from "./RuleCard";
import { cn } from "@/lib/utils";

type Filter = "All" | RuleCategory | "Disabled";
const FILTERS: Filter[] = [
  "All",
  "Escalation",
  "Handoff",
  "Throttle",
  "Compliance",
  "Routing",
  "Disabled",
];

type Props = {
  rules: Rule[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggle: (id: string, v: boolean) => void;
  onEdit: (id: string) => void;
  onDuplicate: (id: string) => void;
  onDelete: (id: string) => void;
  onReorder: (fromIdx: number, toIdx: number) => void;
};

export function RuleList(props: Props) {
  const [filter, setFilter] = useState<Filter>("All");
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  const filtered = props.rules
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => {
      if (filter === "All") return true;
      if (filter === "Disabled") return !r.enabled;
      return r.category === filter;
    });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-075 border-b border-border bg-surface px-150 py-100">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-full border px-150 py-050 text-body-small font-medium transition-colors",
              filter === f
                ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                : "border-border bg-surface text-text-subtle hover:border-border-brand/40",
            )}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 space-y-100 overflow-y-auto p-150">
        {filtered.length === 0 && (
          <div className="rounded-large border border-dashed border-border p-400 text-center text-body-small text-text-subtlest">
            No rules match this filter.
          </div>
        )}
        {filtered.map(({ r, i }) => (
          <RuleCard
            key={r.id}
            rule={r}
            priority={i + 1}
            selected={props.selectedId === r.id}
            onSelect={() => props.onSelect(r.id)}
            onToggle={(v) => props.onToggle(r.id, v)}
            onEdit={() => props.onEdit(r.id)}
            onDuplicate={() => props.onDuplicate(r.id)}
            onDelete={() => props.onDelete(r.id)}
            onDragStart={() => setDragIdx(i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (dragIdx !== null && dragIdx !== i) props.onReorder(dragIdx, i);
              setDragIdx(null);
            }}
          />
        ))}
      </div>
    </div>
  );
}
