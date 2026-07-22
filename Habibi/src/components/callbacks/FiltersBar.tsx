import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  REASON_LABELS,
  STATUS_LABELS,
  type CbChannel,
  type CbReason,
  type CbStatus,
  type Filters,
} from "@/data/callbacks-seed";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  /** Live: real DB humans (+ Unassigned). Mock: seed AGENTS. */
  assignees: string[];
  /** Live: real DB teams. Mock: seed QUEUES. */
  queues: string[];
  myQueue: string;
}

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px]",
        on
          ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold"
          : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
      )}
    >
      {label}
    </button>
  );
}

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

const REASONS: CbReason[] = ["payment_discussion", "dispute_followup", "document_query", "hardship_review", "upsell_interest", "general"];
const STATUSES: CbStatus[] = ["scheduled", "reminded", "in_progress", "completed", "missed", "cancelled"];
const CHANNELS: CbChannel[] = ["whatsapp", "sms", "email"];

export function FiltersBar({ filters, onPatch, onReset, assignees, queues, myQueue }: Props) {
  const activeCount =
    filters.reasons.length +
    filters.statuses.length +
    filters.channels.length +
    (filters.queue !== "all" ? 1 : 0) +
    (filters.assignee !== "all" ? 1 : 0) +
    (filters.dndSafeOnly ? 1 : 0) +
    (filters.myQueueOnly ? 1 : 0) +
    (filters.search ? 1 : 0);

  return (
    <div className="shrink-0 rounded-lg border border-[var(--border-token)] bg-surface-card px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <Input
            value={filters.search}
            onChange={(e) => onPatch({ search: e.target.value })}
            placeholder="Search customer, account, ID…"
            className="h-8 pl-7 text-[12px]"
          />
        </div>
        <select
          value={filters.queue}
          onChange={(e) => onPatch({ queue: e.target.value })}
          className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
        >
          <option value="all">All queues</option>
          {queues.map((q) => <option key={q} value={q}>{q}</option>)}
        </select>
        <select
          value={filters.assignee}
          onChange={(e) => onPatch({ assignee: e.target.value })}
          className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
        >
          <option value="all">All assignees</option>
          {assignees.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <Chip
          on={filters.myQueueOnly}
          label={`My queue · ${myQueue}`}
          onClick={() => onPatch({ myQueueOnly: !filters.myQueueOnly })}
        />
        <Chip
          on={filters.dndSafeOnly}
          label="DND-safe only"
          onClick={() => onPatch({ dndSafeOnly: !filters.dndSafeOnly })}
        />
        {activeCount > 0 && (
          <Button variant="ghost" size="sm" className="h-8 text-[11px]" onClick={onReset}>
            <X className="mr-1 h-3 w-3" /> Reset ({activeCount})
          </Button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[10.5px] uppercase tracking-wide text-text-muted mr-1">Reason</span>
        {REASONS.map((r) => (
          <Chip key={r} on={filters.reasons.includes(r)} label={REASON_LABELS[r]} onClick={() => onPatch({ reasons: toggle(filters.reasons, r) })} />
        ))}
        <span className="text-[10.5px] uppercase tracking-wide text-text-muted mx-2">Status</span>
        {STATUSES.map((s) => (
          <Chip key={s} on={filters.statuses.includes(s)} label={STATUS_LABELS[s]} onClick={() => onPatch({ statuses: toggle(filters.statuses, s) })} />
        ))}
        <span className="text-[10.5px] uppercase tracking-wide text-text-muted mx-2">Reminder</span>
        {CHANNELS.map((c) => (
          <Chip key={c} on={filters.channels.includes(c)} label={CHANNEL_LABELS[c]} onClick={() => onPatch({ channels: toggle(filters.channels, c) })} />
        ))}
      </div>
    </div>
  );
}
