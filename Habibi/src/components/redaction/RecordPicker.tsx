import { Search, Phone, MessageCircle, MessageSquare } from "lucide-react";
import type { RedactionRecord, RecordFilter } from "@/data/redaction-seed";
import { formatDateTime } from "@/data/redaction-seed";
import { cn } from "@/lib/utils";

interface Props {
  records: RedactionRecord[];
  filter: RecordFilter;
  onFilter: (f: RecordFilter) => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onSelectAllWithPii: () => void;
  onClearSelection: () => void;
  activeId: string | null;
  onOpen: (id: string) => void;
}

const CH_ICON = { voice: Phone, whatsapp: MessageCircle, sms: MessageSquare } as const;

export function RecordPicker(p: Props) {
  return (
    <div className="flex h-full min-h-0 w-[320px] shrink-0 flex-col border-r border-[var(--border-token)] bg-surface-card">
      <div className="shrink-0 space-y-2 border-b border-[var(--border-token)] px-3 py-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <input
            value={p.filter.q}
            onChange={(e) => p.onFilter({ ...p.filter, q: e.target.value })}
            placeholder="Search call, customer, record ID"
            className="w-full rounded-md border border-[var(--border-token)] bg-surface-sunken py-1.5 pl-7 pr-2 text-[12px] focus:border-brand-primary focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {(["all", "voice", "whatsapp", "sms"] as const).map((c) => (
            <button
              key={c}
              onClick={() => p.onFilter({ ...p.filter, channel: c })}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] capitalize transition-colors",
                p.filter.channel === c
                  ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                  : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {c}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-1 text-[11px] text-text-secondary">
            <input
              type="checkbox"
              checked={p.filter.hasPiiOnly}
              onChange={(e) => p.onFilter({ ...p.filter, hasPiiOnly: e.target.checked })}
              className="h-3 w-3 accent-[var(--brand-primary)]"
            />
            Has PII
          </label>
        </div>
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-text-muted">{p.records.length} records</span>
          <div className="flex gap-2">
            <button onClick={p.onSelectAllWithPii} className="text-brand-primary hover:underline">Select all w/ PII</button>
            {p.selected.size > 0 && (
              <button onClick={p.onClearSelection} className="text-text-secondary hover:underline">Clear ({p.selected.size})</button>
            )}
          </div>
        </div>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {p.records.map((r) => {
          const Icon = CH_ICON[r.channel];
          const active = p.activeId === r.id;
          const isSelected = p.selected.has(r.id);
          const piiCount = r.findings.length;
          return (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => p.onOpen(r.id)}
                className={cn(
                  "flex w-full items-start gap-2 border-b border-[var(--border-token)] px-3 py-2 text-left transition-colors hover:bg-surface-sunken",
                  active && "bg-brand-tint hover:bg-brand-tint",
                )}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => p.onToggle(r.id)}
                  className="mt-1 h-3.5 w-3.5 accent-[var(--brand-primary)]"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <Icon className="h-3 w-3 text-text-muted" />
                    <span className="truncate text-[12px] font-semibold text-brand-navy">{r.customer}</span>
                    <span className="ml-auto text-[10px] text-text-muted">{r.id}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-muted">
                    <span>{formatDateTime(r.occurredAt)}</span>
                    <span>·</span>
                    <span className="truncate">{r.handler}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-1">
                    <span
                      className={cn(
                        "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                        piiCount > 0
                          ? "bg-[var(--danger-bg)] text-[var(--danger)]"
                          : "bg-[var(--success-bg)] text-[var(--success)]",
                      )}
                    >
                      {piiCount} PII
                    </span>
                    {r.reviewed && (
                      <span className="rounded-full bg-[var(--success-bg)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--success)]">
                        Reviewed
                      </span>
                    )}
                  </div>
                </div>
              </button>
            </li>
          );
        })}
        {p.records.length === 0 && (
          <li className="px-4 py-6 text-center text-[12px] text-text-muted">No records match filters</li>
        )}
      </ul>
    </div>
  );
}
