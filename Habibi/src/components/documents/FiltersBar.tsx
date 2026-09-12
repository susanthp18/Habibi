import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Chip } from "@/components/ui/chip";
import { FiltersBar as Bar, FilterGroup } from "@/components/records/FiltersBar";
import { toggleIn } from "@/lib/utils";
import type { DocChannel, DocType, DocumentFilters, RequestedVia } from "@/api/types/documents";
import { CHANNEL_LABELS, DOC_TYPE_LABELS, VIA_LABELS } from "@/lib/documents";

interface Props {
  filters: DocumentFilters;
  onPatch: (p: Partial<DocumentFilters>) => void;
  onReset: () => void;
  assignees: string[];
}

const DOC_TYPES = Object.keys(DOC_TYPE_LABELS) as DocType[];

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
    <Bar
      search={filters.search}
      onSearch={(search) => onPatch({ search })}
      placeholder="Search customer, account, request id…"
      activeCount={activeCount}
      onReset={onReset}
    >
      <FilterGroup label="Type">
        {DOC_TYPES.slice(0, 4).map((t) => (
          <Chip
            key={t}
            active={filters.docTypes.includes(t)}
            onClick={() => onPatch({ docTypes: toggleIn(filters.docTypes, t) })}
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
            {DOC_TYPES.slice(4).map((t) => (
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
      </FilterGroup>

      <FilterGroup label="Channel">
        {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
          <Chip
            key={c}
            active={filters.channels.includes(c)}
            onClick={() => onPatch({ channels: toggleIn(filters.channels, c) })}
          >
            {CHANNEL_LABELS[c]}
          </Chip>
        ))}
      </FilterGroup>

      <FilterGroup label="Via">
        {(Object.keys(VIA_LABELS) as RequestedVia[]).map((v) => (
          <Chip
            key={v}
            active={filters.vias.includes(v)}
            onClick={() => onPatch({ vias: toggleIn(filters.vias, v) })}
          >
            {VIA_LABELS[v]}
          </Chip>
        ))}
      </FilterGroup>

      <FilterGroup label="Range">
        {(["today", "7d", "30d", "all"] as const).map((r) => (
          <Chip key={r} active={filters.range === r} onClick={() => onPatch({ range: r })}>
            {r === "all" ? "All" : r}
          </Chip>
        ))}
      </FilterGroup>

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
    </Bar>
  );
}
