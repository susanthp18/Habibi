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
        "rounded-full border px-100 py-025 text-body-small",
        on
          ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
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
    <div className="shrink-0 rounded-large border border-border bg-surface px-150 py-100">
      <div className="flex flex-wrap items-center gap-100">
        <div className="relative flex-1 min-w-[13.75rem]">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <Input
            value={filters.search}
            onChange={(e) => onPatch({ search: e.target.value })}
            placeholder="Search customer, account, request id…"
            className="h-400 pl-400 text-body-small"
          />
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Type</span>
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
            className="h-300 rounded-medium border border-border bg-surface px-050 text-body-small"
          >
            <option value="">+ more</option>
            {(Object.keys(DOC_TYPE_LABELS) as DocType[]).slice(4).map((t) => (
              <option key={t} value={t}>
                {DOC_TYPE_LABELS[t]} {filters.docTypes.includes(t) ? "✓" : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Channel</span>
          {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
            <Chip
              key={c}
              label={CHANNEL_LABELS[c]}
              on={filters.channels.includes(c)}
              onClick={() => onPatch({ channels: toggle(filters.channels, c) })}
            />
          ))}
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Via</span>
          {(Object.keys(VIA_LABELS) as RequestedVia[]).map((v) => (
            <Chip
              key={v}
              label={VIA_LABELS[v]}
              on={filters.vias.includes(v)}
              onClick={() => onPatch({ vias: toggle(filters.vias, v) })}
            />
          ))}
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Range</span>
          {(["today", "7d", "30d", "all"] as const).map((r) => (
            <Chip
              key={r}
              label={r === "all" ? "All" : r}
              on={filters.range === r}
              onClick={() => onPatch({ range: r })}
            />
          ))}
        </div>

        <select
          value={filters.assignee}
          onChange={(e) => onPatch({ assignee: e.target.value })}
          className="h-7 rounded-medium border border-border bg-surface px-100 text-body-small"
        >
          <option value="all">All assignees</option>
          {assignees.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        {activeCount > 0 && (
          <Button size="sm" variant="ghost" className="h-7 text-body-small" onClick={onReset}>
            <X className="mr-050 h-3 w-3" /> Clear
          </Button>
        )}
      </div>
    </div>
  );
}
