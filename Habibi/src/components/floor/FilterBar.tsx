import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { topicOptions, type Channel, type HandlerKind } from "@/data/floor-seed";

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
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--border-token)] bg-surface-card px-4 py-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
        <input
          type="text"
          placeholder="Search customer, agent, account…"
          value={value.q}
          onChange={(e) => patch({ q: e.target.value })}
          className="h-8 w-56 rounded-md border border-[var(--border-token)] bg-surface-sunken pl-7 pr-2 text-[12px] text-text-primary focus:border-brand-primary focus:outline-none"
        />
      </div>

      <div className="flex items-center gap-1">
        {(["voice", "whatsapp", "sms"] as Channel[]).map((c) => {
          const on = value.channels.includes(c);
          return (
            <button
              key={c}
              type="button"
              onClick={() => toggleChannel(c)}
              className={cn(
                "rounded-full border px-2 py-1 text-[11px] font-medium capitalize transition-colors",
                on
                  ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                  : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
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

      <div className="ml-auto tabular rounded-full bg-surface-sunken px-2.5 py-1 text-[11px] font-semibold text-text-secondary">
        {visibleCount} / {totalCount} live
      </div>
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
    <label className="flex items-center gap-1 text-[11px] text-text-muted">
      <span className="hidden sm:inline">{label}:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px] text-text-primary focus:border-brand-primary focus:outline-none"
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
