import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  SOURCE_LABELS,
  TEAM_OPTIONS,
  products,
  type Filters,
  type LeadSource,
  type Priority,
  type Sentiment,
} from "@/data/upsell-seed";
import { cn } from "@/lib/utils";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  owners: string[];
}

const SENTIMENTS: Sentiment[] = ["positive", "neutral", "negative"];
const PRIORITIES: Priority[] = ["high", "normal", "low"];
const SOURCES = Object.keys(SOURCE_LABELS) as LeadSource[];

const sentimentTone: Record<Sentiment, string> = {
  positive: "border-emerald-400 bg-emerald-50 text-emerald-700",
  neutral: "border-slate-300 bg-slate-50 text-slate-700",
  negative: "border-red-400 bg-red-50 text-red-700",
};

const priorityTone: Record<Priority, string> = {
  high: "border-amber-500 bg-amber-50 text-amber-700",
  normal: "border-brand-primary bg-brand-tint text-brand-primary-dark",
  low: "border-slate-300 bg-slate-50 text-slate-700",
};

export function FiltersBar({ filters, onPatch, onReset, owners }: Props) {
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
    const next = filters.sentiments.includes(s) ? filters.sentiments.filter((x) => x !== s) : [...filters.sentiments, s];
    onPatch({ sentiments: next });
  };
  const togglePriority = (p: Priority) => {
    const next = filters.priorities.includes(p) ? filters.priorities.filter((x) => x !== p) : [...filters.priorities, p];
    onPatch({ priorities: next });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border-token)] bg-surface-card p-2">
      <div className="relative min-w-[220px] flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
        <Input
          value={filters.search}
          onChange={(e) => onPatch({ search: e.target.value })}
          placeholder="Search customer, account, product, snippet, lead ID…"
          className="h-8 pl-7 text-[12px]"
        />
      </div>

      <select
        value={filters.team}
        onChange={(e) => onPatch({ team: e.target.value as Filters["team"] })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        <option value="all">All teams</option>
        {TEAM_OPTIONS.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <select
        value={filters.owner}
        onChange={(e) => onPatch({ owner: e.target.value })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        <option value="all">All owners</option>
        {owners.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>

      <select
        value={filters.productId}
        onChange={(e) => onPatch({ productId: e.target.value })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        <option value="all">All products</option>
        {products.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      <select
        value={filters.source}
        onChange={(e) => onPatch({ source: e.target.value as Filters["source"] })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        <option value="all">All sources</option>
        {SOURCES.map((s) => (
          <option key={s} value={s}>{SOURCE_LABELS[s]}</option>
        ))}
      </select>

      <div className="flex items-center gap-1">
        {SENTIMENTS.map((s) => {
          const on = filters.sentiments.includes(s);
          return (
            <button
              key={s}
              onClick={() => toggleSentiment(s)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[11px] capitalize transition-colors",
                on ? sentimentTone[s] : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {s}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-1">
        {PRIORITIES.map((p) => {
          const on = filters.priorities.includes(p);
          return (
            <button
              key={p}
              onClick={() => togglePriority(p)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[11px] capitalize transition-colors",
                on ? priorityTone[p] : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
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
          "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
          filters.myQueue
            ? "border-brand-primary bg-brand-primary text-white"
            : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
        )}
      >
        My leads
      </button>

      {active && (
        <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={onReset}>
          <X className="mr-1 h-3 w-3" /> Reset
        </Button>
      )}
    </div>
  );
}
