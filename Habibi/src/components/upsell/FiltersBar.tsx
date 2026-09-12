import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import type { Filters, LeadSource, Priority, Product, Sentiment } from "@/api/types/upsell";
import { SOURCE_LABELS } from "@/lib/upsell";
import { cn } from "@/lib/utils";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  owners: string[];
  products: Product[];
  teams: string[];
}

const SENTIMENTS: Sentiment[] = ["positive", "neutral", "negative"];
const PRIORITIES: Priority[] = ["high", "normal", "low"];
const SOURCES = Object.keys(SOURCE_LABELS) as LeadSource[];

const sentimentTone: Record<Sentiment, string> = {
  positive: "border-border-success bg-background-success-subtler text-text-success-bolder",
  neutral:
    "border-border-accent-gray bg-background-accent-gray-subtlest text-text-accent-gray-bolder",
  negative: "border-border-danger bg-background-danger-subtler text-text-danger-bolder",
};

const priorityTone: Record<Priority, string> = {
  high: "border-border-warning bg-background-warning-subtler text-text-warning-bolder",
  normal: "border-border-brand bg-background-brand-subtlest text-text-brand",
  low: "border-border-accent-gray bg-background-accent-gray-subtlest text-text-accent-gray-bolder",
};

export function FiltersBar({ filters, onPatch, onReset, owners, products, teams }: Props) {
  const active =
    !!filters.search ||
    filters.team !== "all" ||
    filters.owner !== "all" ||
    filters.productId !== "all" ||
    filters.source !== "all" ||
    filters.sentiments.length > 0 ||
    filters.priorities.length > 0 ||
    filters.myQueue;

  const toggleSentiment = (s: Sentiment) => {
    const next = filters.sentiments.includes(s)
      ? filters.sentiments.filter((x) => x !== s)
      : [...filters.sentiments, s];
    onPatch({ sentiments: next });
  };
  const togglePriority = (p: Priority) => {
    const next = filters.priorities.includes(p)
      ? filters.priorities.filter((x) => x !== p)
      : [...filters.priorities, p];
    onPatch({ priorities: next });
  };

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-100 rounded-large border border-border bg-surface p-100">
      <div className="relative min-w-[13.75rem] flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
        <Input
          value={filters.search}
          onChange={(e) => onPatch({ search: e.target.value })}
          placeholder="Search customer, account, product, snippet, lead ID…"
          size="compact"
          className="pl-400"
        />
      </div>

      <SelectField
        aria-label="Team"
        value={filters.team}
        onChange={(v) => onPatch({ team: v as Filters["team"] })}
        size="compact"
        className="w-[8.125rem]"
        options={[
          { value: "all", label: "All teams" },
          ...teams.map((t) => ({ value: t, label: t })),
        ]}
      />

      <SelectField
        aria-label="Owner"
        value={filters.owner}
        onChange={(v) => onPatch({ owner: v })}
        size="compact"
        className="w-[8.75rem]"
        options={[
          { value: "all", label: "All owners" },
          ...owners.map((o) => ({ value: o, label: o })),
        ]}
      />

      <SelectField
        aria-label="Product"
        value={filters.productId}
        onChange={(v) => onPatch({ productId: v })}
        size="compact"
        className="w-[9.375rem]"
        options={[
          { value: "all", label: "All products" },
          ...products.map((p) => ({ value: p.id, label: p.name })),
        ]}
      />

      <SelectField
        aria-label="Source"
        value={filters.source}
        onChange={(v) => onPatch({ source: v as Filters["source"] })}
        size="compact"
        className="w-[8.75rem]"
        options={[
          { value: "all", label: "All sources" },
          ...SOURCES.map((s) => ({ value: s, label: SOURCE_LABELS[s] })),
        ]}
      />

      <div className="flex items-center gap-050">
        {SENTIMENTS.map((s) => {
          const on = filters.sentiments.includes(s);
          return (
            <button
              key={s}
              onClick={() => toggleSentiment(s)}
              className={cn(
                "rounded-full border px-150 py-050 text-body-small capitalize transition-colors",
                on
                  ? sentimentTone[s]
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {s}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-050">
        {PRIORITIES.map((p) => {
          const on = filters.priorities.includes(p);
          return (
            <button
              key={p}
              onClick={() => togglePriority(p)}
              className={cn(
                "rounded-full border px-150 py-050 text-body-small capitalize transition-colors",
                on
                  ? priorityTone[p]
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {p}
            </button>
          );
        })}
      </div>

      <button
        onClick={() => onPatch({ myQueue: !filters.myQueue })}
        className={cn(
          "rounded-full border px-150 py-050 text-body-small transition-colors",
          filters.myQueue
            ? "border-border-brand bg-background-brand-bold text-white"
            : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
        )}
      >
        My leads
      </button>

      {active && (
        <Button size="sm" variant="ghost" className="h-400" onClick={onReset}>
          <X className="mr-050 h-3 w-3" /> Reset
        </Button>
      )}
    </div>
  );
}
