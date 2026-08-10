import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  SOURCE_LABELS,
  TYPE_LABELS,
  type DisputeSource,
  type DisputeType,
  type Filters,
} from "@/data/disputes-seed";
import { cn } from "@/lib/utils";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  assignees: string[];
}

const TYPES = Object.keys(TYPE_LABELS) as DisputeType[];
const SOURCES = Object.keys(SOURCE_LABELS) as DisputeSource[];

export function FiltersBar({ filters, onPatch, onReset, assignees }: Props) {
  const active =
    !!filters.search ||
    filters.types.length > 0 ||
    filters.sources.length > 0 ||
    filters.assignee !== "all" ||
    filters.sla !== "all" ||
    filters.amount !== "any" ||
    filters.myQueue;

  const toggleType = (t: DisputeType) => {
    const next = filters.types.includes(t) ? filters.types.filter((x) => x !== t) : [...filters.types, t];
    onPatch({ types: next });
  };
  const toggleSource = (s: DisputeSource) => {
    const next = filters.sources.includes(s) ? filters.sources.filter((x) => x !== s) : [...filters.sources, s];
    onPatch({ sources: next });
  };

  return (
    <div className="flex flex-wrap items-center gap-100 rounded-large border border-border bg-surface p-100">
      <div className="relative min-w-[13.75rem] flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
        <Input
          value={filters.search}
          onChange={(e) => onPatch({ search: e.target.value })}
          placeholder="Search customer, account, snippet, dispute ID…"
          className="h-400 pl-400 text-body-small"
        />
      </div>

      <div className="flex items-center gap-050">
        {SOURCES.map((s) => (
          <button
            key={s}
            onClick={() => toggleSource(s)}
            className={cn(
              "rounded-full border px-150 py-050 text-body-small transition-colors",
              filters.sources.includes(s)
                ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
            )}
          >
            {SOURCE_LABELS[s]}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-050">
        {(["all", "at_risk", "breached"] as const).map((s) => (
          <button
            key={s}
            onClick={() => onPatch({ sla: s })}
            className={cn(
              "rounded-full border px-150 py-050 text-body-small transition-colors",
              filters.sla === s
                ? s === "breached"
                  ? "border-border-danger bg-background-danger-subtler text-text-danger-bolder"
                  : s === "at_risk"
                    ? "border-border-warning bg-background-warning-subtler text-text-warning-bolder"
                    : "border-border-brand bg-background-brand-subtlest text-text-brand"
                : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
            )}
          >
            SLA · {s === "all" ? "All" : s === "at_risk" ? "At risk" : "Breached"}
          </button>
        ))}
      </div>

      <select
        value={filters.amount}
        onChange={(e) => onPatch({ amount: e.target.value as Filters["amount"] })}
        className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
      >
        <option value="any">Any amount</option>
        <option value="lt5">Under ₹5k</option>
        <option value="5to25">₹5k – ₹25k</option>
        <option value="gt25">Over ₹25k</option>
      </select>

      <select
        value={filters.assignee}
        onChange={(e) => onPatch({ assignee: e.target.value })}
        className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
      >
        <option value="all">All assignees</option>
        {assignees.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>

      <button
        onClick={() => onPatch({ myQueue: !filters.myQueue })}
        className={cn(
          "rounded-full border px-150 py-050 text-body-small transition-colors",
          filters.myQueue
            ? "border-border-brand bg-background-brand-bold text-white"
            : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
        )}
      >
        My queue
      </button>

      <details className="relative">
        <summary className="cursor-pointer list-none rounded-medium border border-border bg-surface px-100 py-050 text-body-small text-text-subtle hover:bg-surface-sunken">
          Type {filters.types.length > 0 && `(${filters.types.length})`}
        </summary>
        <div className="absolute right-0 z-20 mt-050 w-56 rounded-medium border border-border bg-surface p-100 shadow-overlay">
          {TYPES.map((t) => (
            <label key={t} className="flex cursor-pointer items-center gap-100 rounded px-100 py-050 text-body-small hover:bg-surface-sunken">
              <input
                type="checkbox"
                checked={filters.types.includes(t)}
                onChange={() => toggleType(t)}
              />
              {TYPE_LABELS[t]}
            </label>
          ))}
        </div>
      </details>

      {active && (
        <Button size="sm" variant="ghost" className="h-7 px-100 text-body-small" onClick={onReset}>
          <X className="mr-050 h-3 w-3" /> Reset
        </Button>
      )}
    </div>
  );
}
