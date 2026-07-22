import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  RULES,
  type ComplianceFilterState,
  type Severity,
  type ViolationStatus,
  listActorNames,
  type Violation,
} from "@/data/compliance-seed";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
const SEV_COLORS: Record<Severity, string> = {
  critical: "bg-[color:var(--danger)] text-white border-transparent",
  high: "bg-[color:var(--warning)] text-white border-transparent",
  medium: "bg-[color:var(--sentiment-neutral)] text-white border-transparent",
  low: "bg-surface-sunken text-text-primary border-[var(--border-token)]",
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
    <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <Input
            value={filters.q}
            onChange={(e) => patch({ q: e.target.value })}
            placeholder="Search snippet, customer, call ID…"
            className="h-9 pl-8 text-[13px]"
          />
        </div>

        <select
          value={filters.dateRange}
          onChange={(e) => patch({ dateRange: e.target.value as ComplianceFilterState["dateRange"] })}
          className="h-9 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px]"
        >
          <option value="today">Today</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="all">All time</option>
        </select>

        <select
          value={filters.ruleId}
          onChange={(e) => patch({ ruleId: e.target.value })}
          className="h-9 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px] max-w-[240px]"
        >
          <option value="all">All rules</option>
          {RULES.map((r) => (
            <option key={r.id} value={r.id}>
              {r.code} · {r.label}
            </option>
          ))}
        </select>

        <select
          value={filters.actor}
          onChange={(e) => patch({ actor: e.target.value as ComplianceFilterState["actor"] })}
          className="h-9 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px]"
        >
          <option value="all">Bot & human</option>
          <option value="bot">Bot only</option>
          <option value="human">Human only</option>
        </select>

        <select
          value={filters.agent}
          onChange={(e) => patch({ agent: e.target.value })}
          className="h-9 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px] max-w-[180px]"
        >
          <option value="all">All actors</option>
          {agents.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>

        <select
          value={filters.status}
          onChange={(e) => patch({ status: e.target.value as "all" | ViolationStatus })}
          className="h-9 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px]"
        >
          <option value="all">Any status</option>
          <option value="open">Open</option>
          <option value="in_review">In review</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </select>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="h-9 gap-1 text-text-secondary"
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

        <div className="ml-auto text-[12px] text-text-secondary">
          <span className="font-semibold text-brand-navy">{resultCount}</span> violation{resultCount === 1 ? "" : "s"}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] uppercase tracking-wider text-text-muted mr-1">Severity</span>
        {SEVERITIES.map((s) => {
          const active = filters.severities.has(s);
          return (
            <button
              key={s}
              onClick={() => toggleSev(s)}
              className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize transition-colors ${
                active ? SEV_COLORS[s] : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken"
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
