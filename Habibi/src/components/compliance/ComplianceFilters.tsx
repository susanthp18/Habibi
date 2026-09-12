import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import type {
  ComplianceFilterState,
  Severity,
  ViolationStatus,
  Violation,
} from "@/api/types/compliance";
import { groupByRule, listActorNames } from "@/lib/compliance";

const RANGE_OPTIONS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "all", label: "All time" },
];
const ACTOR_OPTIONS = [
  { value: "all", label: "Bot & human" },
  { value: "bot", label: "Bot only" },
  { value: "human", label: "Human only" },
];
const STATUS_OPTIONS = [
  { value: "all", label: "Any status" },
  { value: "open", label: "Open" },
  { value: "in_review", label: "In review" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
];

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
const SEV_COLORS: Record<Severity, string> = {
  critical: "bg-[color:var(--danger)] text-white border-transparent",
  high: "bg-[color:var(--warning)] text-white border-transparent",
  medium: "bg-[color:var(--sentiment-neutral)] text-white border-transparent",
  low: "bg-surface-sunken text-text border-border",
};

export function ComplianceFilters({
  filters,
  onChange,
  all,
  resultCount,
}: {
  filters: ComplianceFilterState;
  onChange: (f: ComplianceFilterState) => void;
  all: Violation[];
  resultCount: number;
}) {
  const agents = listActorNames(all);
  const rules = groupByRule(all);
  const patch = (p: Partial<ComplianceFilterState>) => onChange({ ...filters, ...p });
  const toggleSev = (s: Severity) => {
    const next = new Set(filters.severities);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    patch({ severities: next });
  };
  const hasFilters =
    filters.q ||
    filters.severities.size > 0 ||
    filters.ruleId !== "all" ||
    filters.actor !== "all" ||
    filters.agent !== "all" ||
    filters.status !== "all" ||
    filters.dateRange !== "30d";

  return (
    <div className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <div className="relative min-w-[13.75rem] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtlest" />
          <Input
            value={filters.q}
            onChange={(e) => patch({ q: e.target.value })}
            placeholder="Search snippet, customer, call ID…"
            size="compact"
            className="pl-400"
          />
        </div>

        <SelectField
          aria-label="Date range"
          value={filters.dateRange}
          onChange={(v) => patch({ dateRange: v as ComplianceFilterState["dateRange"] })}
          size="compact"
          className="w-[8.75rem]"
          options={RANGE_OPTIONS}
        />

        <SelectField
          aria-label="Rule"
          value={filters.ruleId}
          onChange={(v) => patch({ ruleId: v })}
          size="compact"
          className="w-[15rem]"
          options={[
            { value: "all", label: "All rules" },
            ...rules.map((r) => ({ value: r.ruleId, label: `${r.code} · ${r.label}` })),
          ]}
        />

        <SelectField
          aria-label="Actor kind"
          value={filters.actor}
          onChange={(v) => patch({ actor: v as ComplianceFilterState["actor"] })}
          size="compact"
          className="w-[8.75rem]"
          options={ACTOR_OPTIONS}
        />

        <SelectField
          aria-label="Actor"
          value={filters.agent}
          onChange={(v) => patch({ agent: v })}
          size="compact"
          className="w-[11.25rem]"
          options={[
            { value: "all", label: "All actors" },
            ...agents.map((a) => ({ value: a, label: a })),
          ]}
        />

        <SelectField
          aria-label="Status"
          value={filters.status}
          onChange={(v) => patch({ status: v as "all" | ViolationStatus })}
          size="compact"
          className="w-[9.375rem]"
          options={STATUS_OPTIONS}
        />

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="h-9 gap-050 text-text-subtle"
            onClick={() =>
              onChange({
                q: "",
                dateRange: "30d",
                severities: new Set(),
                ruleId: "all",
                actor: "all",
                agent: "all",
                status: "all",
              })
            }
          >
            <X className="h-3.5 w-3.5" /> Clear
          </Button>
        )}

        <div className="ml-auto text-body-small text-text-subtle">
          <span className="font-semibold text-text">{resultCount}</span> violation
          {resultCount === 1 ? "" : "s"}
        </div>
      </div>

      <div className="mt-100 flex flex-wrap items-center gap-075">
        <span className="text-body-small text-text-subtlest mr-050">Severity</span>
        {SEVERITIES.map((s) => {
          const active = filters.severities.has(s);
          return (
            <button
              key={s}
              onClick={() => toggleSev(s)}
              className={`inline-flex items-center gap-050 rounded-full border px-150 py-025 text-body-small font-medium capitalize transition-colors ${
                active
                  ? SEV_COLORS[s]
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken"
              }`}
            >
              {s}
            </button>
          );
        })}
      </div>
    </div>
  );
}
