import type { Channel, HandlerKind } from "@/api/types/floor";
import { Lozenge } from "@/components/ui/lozenge";
import { Chip } from "@/components/ui/chip";
import { FiltersBar, FilterGroup } from "@/components/records/FiltersBar";
import { toggleIn } from "@/lib/utils";

export type Filters = {
  q: string;
  channels: Channel[];
  handler: HandlerKind | "all";
};

type Props = {
  value: Filters;
  onChange: (next: Filters) => void;
  visibleCount: number;
  totalCount: number;
};

const HANDLERS: [HandlerKind | "all", string][] = [
  ["all", "All handlers"],
  ["bot", "Bot"],
  ["human", "Human"],
];

export function FilterBar({ value, onChange, visibleCount, totalCount }: Props) {
  const patch = (p: Partial<Filters>) => onChange({ ...value, ...p });
  return (
    <FiltersBar
      className="rounded-none border-x-0 border-t-0 px-200"
      search={value.q}
      onSearch={(q) => patch({ q })}
      placeholder="Search customer, agent, account…"
    >
      <FilterGroup>
        {(["voice", "whatsapp", "sms"] as Channel[]).map((c) => (
          <Chip
            key={c}
            className="capitalize"
            active={value.channels.includes(c)}
            onClick={() => patch({ channels: toggleIn(value.channels, c) })}
          >
            {c}
          </Chip>
        ))}
      </FilterGroup>

      <FilterGroup>
        {HANDLERS.map(([v, l]) => (
          <Chip key={v} active={value.handler === v} onClick={() => patch({ handler: v })}>
            {l}
          </Chip>
        ))}
      </FilterGroup>

      <Lozenge tone="neutral" className="ml-auto tabular">
        {visibleCount} / {totalCount} live
      </Lozenge>
    </FiltersBar>
  );
}
