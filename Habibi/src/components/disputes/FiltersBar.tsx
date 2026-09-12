import { SelectField } from "@/components/ui/select";
import { Chip, type ChipTone } from "@/components/ui/chip";
import { FiltersBar as Bar, FilterGroup } from "@/components/records/FiltersBar";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import type { DisputeSource, DisputeType, DisputeFilters } from "@/api/types/disputes";
import { SOURCE_LABELS, TYPE_LABELS } from "@/lib/disputes";
import { toggleIn } from "@/lib/utils";

interface Props {
  filters: DisputeFilters;
  onPatch: (p: Partial<DisputeFilters>) => void;
  onReset: () => void;
  assignees: string[];
}

const AMOUNT_OPTIONS = [
  { value: "any", label: "Any amount" },
  { value: "lt5", label: "Under ₹5k" },
  { value: "5to25", label: "₹5k – ₹25k" },
  { value: "gt25", label: "Over ₹25k" },
];

const SLA: { value: DisputeFilters["sla"]; label: string; tone: ChipTone }[] = [
  { value: "all", label: "All", tone: "brand" },
  { value: "at_risk", label: "At risk", tone: "warning" },
  { value: "breached", label: "Breached", tone: "danger" },
];

const TYPES = Object.keys(TYPE_LABELS) as DisputeType[];
const SOURCES = Object.keys(SOURCE_LABELS) as DisputeSource[];

export function FiltersBar({ filters, onPatch, onReset, assignees }: Props) {
  const activeCount =
    (filters.search ? 1 : 0) +
    filters.types.length +
    filters.sources.length +
    (filters.assignee !== "all" ? 1 : 0) +
    (filters.sla !== "all" ? 1 : 0) +
    (filters.amount !== "any" ? 1 : 0) +
    (filters.myQueue ? 1 : 0);

  return (
    <Bar
      search={filters.search}
      onSearch={(search) => onPatch({ search })}
      placeholder="Search customer, account, snippet, dispute ID…"
      activeCount={activeCount}
      onReset={onReset}
    >
      <FilterGroup>
        {SOURCES.map((s) => (
          <Chip
            key={s}
            active={filters.sources.includes(s)}
            onClick={() => onPatch({ sources: toggleIn(filters.sources, s) })}
          >
            {SOURCE_LABELS[s]}
          </Chip>
        ))}
      </FilterGroup>

      <FilterGroup>
        {SLA.map((s) => (
          <Chip
            key={s.value}
            active={filters.sla === s.value}
            tone={s.tone}
            onClick={() => onPatch({ sla: s.value })}
          >
            SLA · {s.label}
          </Chip>
        ))}
      </FilterGroup>

      <SelectField
        aria-label="Amount"
        value={filters.amount}
        onChange={(v) => onPatch({ amount: v as DisputeFilters["amount"] })}
        size="compact"
        className="w-[8.75rem]"
        options={AMOUNT_OPTIONS}
      />

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

      <Chip active={filters.myQueue} onClick={() => onPatch({ myQueue: !filters.myQueue })}>
        My queue
      </Chip>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" className="h-400">
            Type {filters.types.length > 0 && `(${filters.types.length})`}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {TYPES.map((t) => (
            <DropdownMenuCheckboxItem
              key={t}
              checked={filters.types.includes(t)}
              onCheckedChange={() => onPatch({ types: toggleIn(filters.types, t) })}
            >
              {TYPE_LABELS[t]}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </Bar>
  );
}
