import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn, toggleIn } from "@/lib/utils";
import { Chip } from "@/components/ui/chip";
import type { DocChannel, DocType, Filters, RequestedVia } from "@/api/types/documents";
import { CHANNEL_LABELS, DOC_TYPE_LABELS, VIA_LABELS } from "@/lib/documents";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  assignees: string[];
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
            size="compact"
            className="pl-400"
          />
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Type</span>
          {(Object.keys(DOC_TYPE_LABELS) as DocType[]).slice(0, 4).map((t) => (
            <Chip
              key={t}
              onClick={() => onPatch({ docTypes: toggleIn(filters.docTypes, t) })}
              active={filters.docTypes.includes(t)}
            >
              {DOC_TYPE_LABELS[t]}
            </Chip>
          ))}
          {/* Toggles several values at once, so it is a checkbox menu and never
              was a select — the "✓" it used to paint into option labels was the
              tell. */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost" className="h-400">
                + more
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {(Object.keys(DOC_TYPE_LABELS) as DocType[]).slice(4).map((t) => (
                <DropdownMenuCheckboxItem
                  key={t}
                  checked={filters.docTypes.includes(t)}
                  onCheckedChange={() => onPatch({ docTypes: toggleIn(filters.docTypes, t) })}
                >
                  {DOC_TYPE_LABELS[t]}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Channel</span>
          {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
            <Chip
              key={c}
              onClick={() => onPatch({ channels: toggleIn(filters.channels, c) })}
              active={filters.channels.includes(c)}
            >
              {CHANNEL_LABELS[c]}
            </Chip>
          ))}
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Via</span>
          {(Object.keys(VIA_LABELS) as RequestedVia[]).map((v) => (
            <Chip
              key={v}
              onClick={() => onPatch({ vias: toggleIn(filters.vias, v) })}
              active={filters.vias.includes(v)}
            >
              {VIA_LABELS[v]}
            </Chip>
          ))}
        </div>

        <div className="flex items-center gap-050">
          <span className="text-body-small text-text-subtlest">Range</span>
          {(["today", "7d", "30d", "all"] as const).map((r) => (
            <Chip key={r} onClick={() => onPatch({ range: r })} active={filters.range === r}>
              {r === "all" ? "All" : r}
            </Chip>
          ))}
        </div>

        <SelectField
          aria-label="Assignee"
          value={filters.assignee}
          onChange={(v) => onPatch({ assignee: v })}
          size="compact"
          className="w-[9.375rem]"
          options={[
            { value: "all", label: "All assignees" },
            ...assignees.map((a) => ({ value: a, label: a })),
          ]}
        />

        {activeCount > 0 && (
          <Button size="sm" variant="ghost" className="h-400" onClick={onReset}>
            <X className="mr-050 h-3 w-3" /> Clear
          </Button>
        )}
      </div>
    </div>
  );
}
