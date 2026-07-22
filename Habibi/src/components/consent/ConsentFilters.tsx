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
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border-token)] bg-surface-card px-5 py-2">
      <div className="relative min-w-[220px] flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
        <input
          value={filters.q}
          onChange={(e) => onChange({ ...filters, q: e.target.value })}
          placeholder="Search name, account, phone, email…"
          className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card pl-7 pr-2 text-[12px] outline-none focus:border-brand-primary"
        />
      </div>

      <select
        value={filters.channel}
        onChange={(e) => onChange({ ...filters, channel: e.target.value as ConsentFilterState["channel"] })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        {CHANNELS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>

      <select
        value={filters.segment}
        onChange={(e) => onChange({ ...filters, segment: e.target.value as ConsentFilterState["segment"] })}
        className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
      >
        {SEGMENTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
      </select>

      <div className="flex flex-wrap gap-1">
        {STATUSES.map((s) => {
          const active = filters.status === s.id;
          return (
            <button
              key={s.id}
              onClick={() => onChange({ ...filters, status: s.id })}
              className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                active
                  ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold"
                  : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken"
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      <div className="ml-auto flex items-center gap-2 text-[11px] text-text-muted">
        <span>{resultCount} / {totalCount}</span>
        {isDirty && (
          <button
            onClick={() => onChange(defaultConsentFilters)}
            className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-brand-primary hover:bg-brand-tint"
          >
            <X className="h-3 w-3" /> Clear
          </button>
        )}
      </div>
    </div>
  );
}
