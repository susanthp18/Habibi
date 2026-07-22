import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  DOC_TYPE_LABELS,
  VIA_LABELS,
  type DocChannel,
  type DocType,
  type Filters,
  type RequestedVia,
} from "@/data/documents-seed";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  assignees: string[];
}

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px]",
        on
          ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold"
          : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
      )}
    >
      {label}
    </button>
  );
}

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

export function FiltersBar({ filters, onPatch, onReset, assignees }: Props) {
  const activeCount =
    filters.docTypes.length +
    filters.channels.length +
    filters.vias.length +
    filters.statuses.length +
    (filters.range !== "all" ? 1 : 0) +
    (filters.assignee !== "all" ? 1 : 0) +
    (filters.search ? 1 : 0);

  return (
    <div className="shrink-0 rounded-lg border border-[var(--border-token)] bg-surface-card px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <Input
            value={filters.search}
            onChange={(e) => onPatch({ search: e.target.value })}
            placeholder="Search customer, account, request id…"
            className="h-8 pl-7 text-[12px]"
          />
        </div>

        <div className="flex items-center gap-1">
          <span className="text-[10.5px] uppercase tracking-wide text-text-muted">Type</span>
          {(Object.keys(DOC_TYPE_LABELS) as DocType[]).slice(0, 4).map((t) => (
            <Chip
              key={t}
              label={DOC_TYPE_LABELS[t]}
              on={filters.docTypes.includes(t)}
              onClick={() => onPatch({ docTypes: toggle(filters.docTypes, t) })}
            />
          ))}
          <select
            value=""
            onChange={(e) => {
              if (!e.target.value) return;
              onPatch({ docTypes: toggle(filters.docTypes, e.target.value as DocType) });
            }}
            className="h-6 rounded-md border border-[var(--border-token)] bg-surface-card px-1 text-[11px]"
          >
            <option value="">+ more</option>
            {(Object.keys(DOC_TYPE_LABELS) as DocType[]).slice(4).map((t) => (
              <option key={t} value={t}>
                {DOC_TYPE_LABELS[t]} {filters.docTypes.includes(t) ? "✓" : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-1">
          <span className="text-[10.5px] uppercase tracking-wide text-text-muted">Channel</span>
          {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
            <Chip
              key={c}
              label={CHANNEL_LABELS[c]}
              on={filters.channels.includes(c)}
              onClick={() => onPatch({ channels: toggle(filters.channels, c) })}
            />
          ))}
        </div>

        <div className="flex items-center gap-1">
          <span className="text-[10.5px] uppercase tracking-wide text-text-muted">Via</span>
          {(Object.keys(VIA_LABELS) as RequestedVia[]).map((v) => (
            <Chip
              key={v}
              label={VIA_LABELS[v]}
              on={filters.vias.includes(v)}
              onClick={() => onPatch({ vias: toggle(filters.vias, v) })}
            />
          ))}
        </div>

        <div className="flex items-center gap-1">
          <span className="text-[10.5px] uppercase tracking-wide text-text-muted">Range</span>
          {(["today", "7d", "30d", "all"] as const).map((r) => (
            <Chip key={r} label={r === "all" ? "All" : r} on={filters.range === r} onClick={() => onPatch({ range: r })} />
          ))}
        </div>

        <select
          value={filters.assignee}
          onChange={(e) => onPatch({ assignee: e.target.value })}
          className="h-7 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
        >
          <option value="all">All assignees</option>
          {assignees.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        {activeCount > 0 && (
          <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={onReset}>
            <X className="mr-1 h-3 w-3" /> Clear
          </Button>
        )}
      </div>
    </div>
  );
}
