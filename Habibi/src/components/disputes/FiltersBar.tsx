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
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border-token)] bg-surface-card p-2">
      <div className="relative min-w-[220px] flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
        <Input
          value={filters.search}
          onChange={(e) => onPatch({ search: e.target.value })}
          placeholder="Search customer, account, snippet, dispute ID…"
          className="h-8 pl-7 text-[12px]"
        />
      </div>

      <div className="flex items-center gap-1">
        {SOURCES.map((s) => (
          <button
            key={s}
            onClick={() => toggleSource(s)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
              filters.sources.includes(s)
                ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
            )}
          >
            {SOURCE_LABELS[s]}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1">
        {(["all", "at_risk", "breached"] as const).map((s) => (
          <button
            key={s}
            onClick={() => onPatch({ sla: s })}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
              filters.sla === s
                ? s === "breached"
                  ? "border-red-500 bg-red-50 text-red-700"
                  : s === "at_risk"
                    ? "border-amber-500 bg-amber-50 text-amber-700"
                    : "border-brand-primary bg-brand-tint text-brand-primary-dark"
                : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
            )}
          >
            SLA · {s === "all" ? "All" : s === "at_risk" ? "At risk" : "Breached"}
          </button>
        ))}
      </div>

      <select
        value={filters.amount}
        onChange={(e) => onPatch({ amount: e.target.value as Filters["amount"] })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        <option value="any">Any amount</option>
        <option value="lt5">Under ₹5k</option>
        <option value="5to25">₹5k – ₹25k</option>
        <option value="gt25">Over ₹25k</option>
      </select>

      <select
        value={filters.assignee}
        onChange={(e) => onPatch({ assignee: e.target.value })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
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
          "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
          filters.myQueue
            ? "border-brand-primary bg-brand-primary text-white"
            : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
        )}
      >
        My queue
      </button>

      <details className="relative">
        <summary className="cursor-pointer list-none rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[11px] text-text-secondary hover:bg-surface-sunken">
          Type {filters.types.length > 0 && `(${filters.types.length})`}
        </summary>
        <div className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-[var(--border-token)] bg-surface-card p-2 shadow-lg">
          {TYPES.map((t) => (
            <label key={t} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[12px] hover:bg-surface-sunken">
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
        <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={onReset}>
          <X className="mr-1 h-3 w-3" /> Reset
        </Button>
      )}
    </div>
  );
}
