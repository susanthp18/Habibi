import { Search, Phone, MessageCircle, MessageSquare } from "lucide-react";
import type { RedactionRecord, RecordFilter } from "@/data/redaction-seed";
import { formatDateTime } from "@/data/redaction-seed";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

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
    <div className="flex h-full min-h-0 w-[20rem] shrink-0 flex-col border-r border-border bg-surface">
      <div className="shrink-0 space-y-100 border-b border-border px-150 py-150">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <input
            value={p.filter.q}
            onChange={(e) => p.onFilter({ ...p.filter, q: e.target.value })}
            placeholder="Search call, customer, record ID"
            className="w-full rounded-medium border border-border bg-surface-sunken py-075 pl-400 pr-100 text-body-small focus:border-border-brand focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap items-center gap-050">
          {(["all", "voice", "whatsapp", "sms"] as const).map((c) => (
            <button
              key={c}
              onClick={() => p.onFilter({ ...p.filter, channel: c })}
              className={cn(
                "rounded-full border px-100 py-025 text-body-small capitalize transition-colors",
                p.filter.channel === c
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                  : "border-border text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {c}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-050 text-body-small text-text-subtle">
            <input
              type="checkbox"
              checked={p.filter.hasPiiOnly}
              onChange={(e) => p.onFilter({ ...p.filter, hasPiiOnly: e.target.checked })}
              className="h-3 w-3 accent-[var(--background-brand-bold)]"
            />
            Has PII
          </label>
        </div>
        <div className="flex items-center justify-between text-body-small">
          <span className="text-text-subtlest">{p.records.length} records</span>
          <div className="flex gap-100">
            <button onClick={p.onSelectAllWithPii} className="text-text-brand hover:underline">
              Select all w/ PII
            </button>
            {p.selected.size > 0 && (
              <button onClick={p.onClearSelection} className="text-text-subtle hover:underline">
                Clear ({p.selected.size})
              </button>
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
                  "flex w-full items-start gap-100 border-b border-border px-150 py-100 text-left transition-colors hover:bg-surface-sunken",
                  active && "bg-background-brand-subtlest hover:bg-background-brand-subtlest",
                )}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => p.onToggle(r.id)}
                  className="mt-050 h-3.5 w-3.5 accent-[var(--background-brand-bold)]"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-075">
                    <Icon className="h-3 w-3 text-text-subtlest" />
                    <span className="truncate text-body-small font-semibold text-text">
                      {r.customer}
                    </span>
                    <span className="ml-auto text-body-small text-text-subtlest">{r.id}</span>
                  </div>
                  <div className="mt-025 flex items-center gap-100 text-body-small text-text-subtlest">
                    <span>{formatDateTime(r.occurredAt)}</span>
                    <span>·</span>
                    <span className="truncate">{r.handler}</span>
                  </div>
                  <div className="mt-050 flex items-center gap-050">
                    <Lozenge tone={piiCount > 0 ? "danger" : "success"}>{piiCount} PII</Lozenge>
                    {r.reviewed && <Lozenge tone="success">Reviewed</Lozenge>}
                  </div>
                </div>
              </button>
            </li>
          );
        })}
        {p.records.length === 0 && (
          <li className="px-200 py-300 text-center text-body-small text-text-subtlest">
            No records match filters
          </li>
        )}
      </ul>
    </div>
  );
}
