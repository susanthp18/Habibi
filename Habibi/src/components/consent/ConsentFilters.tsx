import { Search, X } from "lucide-react";
import { CHANNEL_LABEL, defaultConsentFilters, type ConsentFilterState, type ConsentChannel } from "@/data/consent-seed";

const STATUSES: { id: ConsentFilterState["status"]; label: string }[] = [
  { id: "all", label: "All" },
  { id: "contactable", label: "Contactable now" },
  { id: "dnd", label: "DND" },
  { id: "opted_out", label: "Has opt-out" },
  { id: "expiring", label: "Expiring ≤30d" },
];

const CHANNELS: { id: "all" | ConsentChannel; label: string }[] = [
  { id: "all", label: "All channels" },
  { id: "call", label: CHANNEL_LABEL.call },
  { id: "whatsapp", label: CHANNEL_LABEL.whatsapp },
  { id: "sms", label: CHANNEL_LABEL.sms },
  { id: "email", label: CHANNEL_LABEL.email },
];

const SEGMENTS: { id: ConsentFilterState["segment"]; label: string }[] = [
  { id: "all", label: "All segments" },
  { id: "Retail", label: "Retail" },
  { id: "SME", label: "SME" },
  { id: "Priority", label: "Priority" },
];

export function ConsentFilters({
  filters,
  onChange,
  resultCount,
  totalCount,
}: {
  filters: ConsentFilterState;
  onChange: (f: ConsentFilterState) => void;
  resultCount: number;
  totalCount: number;
}) {
  const isDirty = JSON.stringify(filters) !== JSON.stringify(defaultConsentFilters);
  return (
    <div className="flex flex-wrap items-center gap-100 border-b border-border bg-surface px-250 py-100">
      <div className="relative min-w-[13.75rem] flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
        <input
          value={filters.q}
          onChange={(e) => onChange({ ...filters, q: e.target.value })}
          placeholder="Search name, account, phone, email…"
          className="h-400 w-full rounded-medium border border-border bg-surface pl-400 pr-100 text-body-small outline-none focus:border-border-brand"
        />
      </div>

      <select
        value={filters.channel}
        onChange={(e) => onChange({ ...filters, channel: e.target.value as ConsentFilterState["channel"] })}
        className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
      >
        {CHANNELS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>

      <select
        value={filters.segment}
        onChange={(e) => onChange({ ...filters, segment: e.target.value as ConsentFilterState["segment"] })}
        className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
      >
        {SEGMENTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
      </select>

      <div className="flex flex-wrap gap-050">
        {STATUSES.map((s) => {
          const active = filters.status === s.id;
          return (
            <button
              key={s.id}
              onClick={() => onChange({ ...filters, status: s.id })}
              className={`rounded-full border px-150 py-050 text-body-small transition-colors ${
                active
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken"
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      <div className="ml-auto flex items-center gap-100 text-body-small text-text-subtlest">
        <span>{resultCount} / {totalCount}</span>
        {isDirty && (
          <button
            onClick={() => onChange(defaultConsentFilters)}
            className="inline-flex items-center gap-050 rounded-medium px-100 py-025 text-text-brand hover:bg-background-brand-subtlest"
          >
            <X className="h-3 w-3" /> Clear
          </button>
        )}
      </div>
    </div>
  );
}
