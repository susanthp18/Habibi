import { SelectField } from "@/components/ui/select";
import { Chip, type ChipTone } from "@/components/ui/chip";
import { FiltersBar as Bar, FilterGroup } from "@/components/records/FiltersBar";
import type { Filters, PromiseStatus } from "@/api/types/promises";
import { STATUS_LABELS, STATUS_ORDER } from "@/lib/promises";

interface Props {
  filters: Filters;
  onChange: (patch: Partial<Filters>) => void;
  owners: string[];
  counts: Record<PromiseStatus | "all", number>;
}

const TONE: Record<PromiseStatus, ChipTone> = {
  upcoming: "brand",
  due_today: "warning",
  kept: "success",
  broken: "danger",
  partial: "warning",
};

export function FiltersBar({ filters, onChange, owners, counts }: Props) {
  return (
    <Bar
      search={filters.search}
      onSearch={(search) => onChange({ search })}
      placeholder="Search customer, account, PTP id"
    >
      <FilterGroup>
        <Chip active={filters.status === "all"} onClick={() => onChange({ status: "all" })}>
          All · {counts.all}
        </Chip>
        {STATUS_ORDER.map((s) => (
          <Chip
            key={s}
            tone={TONE[s]}
            active={filters.status === s}
            onClick={() => onChange({ status: s })}
          >
            {STATUS_LABELS[s]} · {counts[s]}
          </Chip>
        ))}
      </FilterGroup>

      <SelectField
        aria-label="Source"
        value={filters.source}
        onChange={(v) => onChange({ source: v as Filters["source"] })}
        size="compact"
        className="w-[8.125rem]"
        options={[
          { value: "all", label: "All sources" },
          { value: "bot", label: "Bot" },
          { value: "agent", label: "Agent" },
          { value: "self", label: "Self-serve" },
        ]}
      />

      <SelectField
        aria-label="Aging"
        value={filters.aging}
        onChange={(v) => onChange({ aging: v as Filters["aging"] })}
        size="compact"
        className="w-[8.125rem]"
        options={[
          { value: "any", label: "Any aging" },
          { value: "3d", label: "Next 3 days" },
          { value: "7d", label: "This week" },
          { value: "gt7", label: "More than 7d out" },
          { value: "overdue", label: "Overdue" },
        ]}
      />

      <SelectField
        aria-label="Amount"
        value={filters.amount}
        onChange={(v) => onChange({ amount: v as Filters["amount"] })}
        size="compact"
        className="w-[8.75rem]"
        options={[
          { value: "any", label: "Any amount" },
          { value: "lt5", label: "Under ₹5,000" },
          { value: "5to25", label: "₹5,000 – ₹25,000" },
          { value: "gt25", label: "Over ₹25,000" },
        ]}
      />

      <SelectField
        aria-label="Owner"
        value={filters.owner}
        onChange={(v) => onChange({ owner: v })}
        size="compact"
        className="w-[8.75rem]"
        options={[
          { value: "all", label: "All owners" },
          ...owners.map((o) => ({ value: o, label: o })),
        ]}
      />
    </Bar>
  );
}
