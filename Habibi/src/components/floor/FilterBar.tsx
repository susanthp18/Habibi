import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { topicOptions, type Channel, type HandlerKind } from "@/data/floor-seed";
import { Lozenge } from "@/components/ui/lozenge";

export type SentimentFilter = "all" | "positive" | "neutral" | "negative";
export type SortKey = "duration" | "sentiment" | "risk";

export type Filters = {
  q: string;
  channels: Channel[];
  handler: HandlerKind | "all";
  sentiment: SentimentFilter;
  topic: string | "all";
  sort: SortKey;
};

type Props = {
  value: Filters;
  onChange: (next: Filters) => void;
  visibleCount: number;
  totalCount: number;
};

export function FilterBar({ value, onChange, visibleCount, totalCount }: Props) {
  const patch = (p: Partial<Filters>) => onChange({ ...value, ...p });

  const toggleChannel = (c: Channel) => {
    const next = value.channels.includes(c)
      ? value.channels.filter((x) => x !== c)
      : [...value.channels, c];
    patch({ channels: next });
  };

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-100 border-b border-border bg-surface px-200 py-100">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
        <input
          type="text"
          placeholder="Search customer, agent, account…"
          value={value.q}
          onChange={(e) => patch({ q: e.target.value })}
          className="h-400 w-56 rounded-medium border border-border bg-surface-sunken pl-400 pr-100 text-body-small text-text focus:border-border-brand focus:outline-none"
        />
      </div>

      <div className="flex items-center gap-050">
        {(["voice", "whatsapp", "sms"] as Channel[]).map((c) => {
          const on = value.channels.includes(c);
          return (
            <button
              key={c}
              type="button"
              onClick={() => toggleChannel(c)}
              className={cn(
                "rounded-full border px-100 py-050 text-body-small font-medium capitalize transition-colors",
                on
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {c}
            </button>
          );
        })}
      </div>

      <Select
        label="Handler"
        value={value.handler}
        onChange={(v) => patch({ handler: v as Filters["handler"] })}
        options={[
          { v: "all", l: "Bot + Human" },
          { v: "bot", l: "Bot only" },
          { v: "human", l: "Human only" },
        ]}
      />

      <Select
        label="Sentiment"
        value={value.sentiment}
        onChange={(v) => patch({ sentiment: v as SentimentFilter })}
        options={[
          { v: "all", l: "All" },
          { v: "positive", l: "Positive" },
          { v: "neutral", l: "Neutral" },
          { v: "negative", l: "Negative" },
        ]}
      />

      <Select
        label="Topic"
        value={value.topic}
        onChange={(v) => patch({ topic: v })}
        options={[
          { v: "all", l: "All topics" },
          ...topicOptions.map((t) => ({ v: t, l: t })),
        ]}
      />

      <Select
        label="Sort"
        value={value.sort}
        onChange={(v) => patch({ sort: v as SortKey })}
        options={[
          { v: "risk", l: "Risk (high→low)" },
          { v: "sentiment", l: "Sentiment (worst first)" },
          { v: "duration", l: "Duration (longest)" },
        ]}
      />

      <Lozenge tone="neutral" className="ml-auto tabular">
        {visibleCount} / {totalCount} live
      </Lozenge>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { v: string; l: string }[];
}) {
  return (
    <label className="flex items-center gap-050 text-body-small text-text-subtlest">
      <span className="hidden sm:inline">{label}:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small text-text focus:border-border-brand focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    </label>
  );
}
