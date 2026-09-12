import { SelectField } from "@/components/ui/select";
import { Chip, type ChipTone } from "@/components/ui/chip";
import { FiltersBar as Bar, FilterGroup } from "@/components/records/FiltersBar";
import type { Filters, LeadSource, Priority, Product, Sentiment } from "@/api/types/upsell";
import { SOURCE_LABELS } from "@/lib/upsell";
import { toggleIn } from "@/lib/utils";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  owners: string[];
  products: Product[];
  teams: string[];
}

const SENTIMENTS: Record<Sentiment, ChipTone> = {
  positive: "success",
  neutral: "neutral",
  negative: "danger",
};
const PRIORITIES: Record<Priority, ChipTone> = { high: "warning", normal: "brand", low: "neutral" };
const SOURCES = Object.keys(SOURCE_LABELS) as LeadSource[];

export function FiltersBar({ filters, onPatch, onReset, owners, products, teams }: Props) {
  const activeCount =
    (filters.search ? 1 : 0) +
    (filters.team !== "all" ? 1 : 0) +
    (filters.owner !== "all" ? 1 : 0) +
    (filters.productId !== "all" ? 1 : 0) +
    (filters.source !== "all" ? 1 : 0) +
    filters.sentiments.length +
    filters.priorities.length +
    (filters.myQueue ? 1 : 0);

  return (
    <Bar
      search={filters.search}
      onSearch={(search) => onPatch({ search })}
      placeholder="Search customer, account, product, snippet, lead ID…"
      activeCount={activeCount}
      onReset={onReset}
    >
      <SelectField
        aria-label="Team"
        value={filters.team}
        onChange={(v) => onPatch({ team: v as Filters["team"] })}
        size="compact"
        className="w-[8.125rem]"
        options={[
          { value: "all", label: "All teams" },
          ...teams.map((t) => ({ value: t, label: t })),
        ]}
      />

      <SelectField
        aria-label="Owner"
        value={filters.owner}
        onChange={(v) => onPatch({ owner: v })}
        size="compact"
        className="w-[8.75rem]"
        options={[
          { value: "all", label: "All owners" },
          ...owners.map((o) => ({ value: o, label: o })),
        ]}
      />

      <SelectField
        aria-label="Product"
        value={filters.productId}
        onChange={(v) => onPatch({ productId: v })}
        size="compact"
        className="w-[9.375rem]"
        options={[
          { value: "all", label: "All products" },
          ...products.map((p) => ({ value: p.id, label: p.name })),
        ]}
      />

      <SelectField
        aria-label="Source"
        value={filters.source}
        onChange={(v) => onPatch({ source: v as Filters["source"] })}
        size="compact"
        className="w-[8.75rem]"
        options={[
          { value: "all", label: "All sources" },
          ...SOURCES.map((s) => ({ value: s, label: SOURCE_LABELS[s] })),
        ]}
      />

      <FilterGroup>
        {(Object.keys(SENTIMENTS) as Sentiment[]).map((s) => (
          <Chip
            key={s}
            className="capitalize"
            tone={SENTIMENTS[s]}
            active={filters.sentiments.includes(s)}
            onClick={() => onPatch({ sentiments: toggleIn(filters.sentiments, s) })}
          >
            {s}
          </Chip>
        ))}
      </FilterGroup>

      <FilterGroup>
        {(Object.keys(PRIORITIES) as Priority[]).map((p) => (
          <Chip
            key={p}
            className="capitalize"
            tone={PRIORITIES[p]}
            active={filters.priorities.includes(p)}
            onClick={() => onPatch({ priorities: toggleIn(filters.priorities, p) })}
          >
            {p}
          </Chip>
        ))}
      </FilterGroup>

      <Chip active={filters.myQueue} onClick={() => onPatch({ myQueue: !filters.myQueue })}>
        My leads
      </Chip>
    </Bar>
  );
}
