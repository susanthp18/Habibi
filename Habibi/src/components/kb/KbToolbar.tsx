import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { DOC_TYPE_LABEL, type KbDocType } from "@/data/kb-seed";
import type { KbTab } from "@/components/kb/KbStatsStrip";

export type KbDocFilters = {
  type: "all" | KbDocType;
  enabled: "all" | "enabled" | "disabled";
};

type Props = {
  tab: KbTab;
  search: string;
  onSearch: (q: string) => void;
  visibleCount: number;
  totalCount: number;
  searchActive: boolean;
  onClear: () => void;
  docTypeOptions: KbDocType[];
  filters: KbDocFilters;
  onFilters: (next: KbDocFilters) => void;
  showResolved: boolean;
  onShowResolved: (v: boolean) => void;
};

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-100 py-050 text-body-small font-medium transition-colors",
        active
          ? "border-border-brand bg-background-brand-subtlest text-text-brand"
          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
      )}
    >
      {children}
    </button>
  );
}

export function KbToolbar({
  tab,
  search,
  onSearch,
  visibleCount,
  totalCount,
  searchActive,
  onClear,
  docTypeOptions,
  filters,
  onFilters,
  showResolved,
  onShowResolved,
}: Props) {
  if (tab === "test") return null;

  const placeholder =
    tab === "faqs"
      ? "Search questions, answers, intents…"
      : tab === "gaps"
        ? "Search unanswered questions…"
        : "Search title, file, tags…";

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-100 border-b border-border bg-surface px-200 py-100">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
        <input
          type="text"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={placeholder}
          aria-label="Filter this list"
          className="h-400 w-56 rounded-medium border border-border bg-surface-sunken pl-400 pr-400 text-body-small text-text focus:border-border-brand focus:outline-none"
        />
        {search && (
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-025 text-text-subtlest hover:text-text"
            onClick={() => onSearch("")}
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {tab === "documents" && (
        <>
          <div className="flex flex-wrap items-center gap-050">
            <Pill active={filters.type === "all"} onClick={() => onFilters({ ...filters, type: "all" })}>
              All types
            </Pill>
            {docTypeOptions.map((t) => (
              <Pill
                key={t}
                active={filters.type === t}
                onClick={() => onFilters({ ...filters, type: filters.type === t ? "all" : t })}
              >
                {DOC_TYPE_LABEL[t]}
              </Pill>
            ))}
          </div>
          <div className="flex items-center gap-050">
            {(
              [
                ["all", "All"],
                ["enabled", "Enabled"],
                ["disabled", "Disabled"],
              ] as const
            ).map(([v, l]) => (
              <Pill
                key={v}
                active={filters.enabled === v}
                onClick={() => onFilters({ ...filters, enabled: v })}
              >
                {l}
              </Pill>
            ))}
          </div>
        </>
      )}

      {tab === "gaps" && (
        <>
          <label className="flex items-center gap-100 text-body-small text-text-subtle">
            <Switch aria-label="Show resolved" checked={showResolved} onCheckedChange={onShowResolved} />
            Show resolved
          </label>
          <Link
            to="/bot-analytics"
            className="text-body-small font-medium text-text-brand hover:underline"
          >
            Open bot analytics
          </Link>
        </>
      )}

      <Lozenge tone="neutral" className="ml-auto tabular">
        {visibleCount} / {totalCount}
      </Lozenge>
      {searchActive && (
        <button
          type="button"
          className="text-body-small font-medium text-text-brand hover:underline"
          onClick={onClear}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
