import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CbChannel, CbReason, CbStatus, Filters } from "@/api/types/callbacks";
import { CHANNEL_LABELS, REASON_LABELS, STATUS_LABELS } from "@/data/callbacks-seed";

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
        "rounded-full border px-100 py-025 text-body-small",
        on
          ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
      )}
    >
      {label}
    </button>
  );
}

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

const REASONS: CbReason[] = [
  "payment_discussion",
  "dispute_followup",
  "document_query",
  "hardship_review",
  "upsell_interest",
  "general",
];
const STATUSES: CbStatus[] = [
  "scheduled",
  "reminded",
  "in_progress",
  "completed",
  "missed",
  "cancelled",
];
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
    <div className="shrink-0 rounded-large border border-border bg-surface px-150 py-100">
      <div className="flex flex-wrap items-center gap-100">
        <div className="relative flex-1 min-w-[13.75rem]">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <Input
            value={filters.search}
            onChange={(e) => onPatch({ search: e.target.value })}
            placeholder="Search customer, account, ID…"
            size="compact"
            className="pl-400"
          />
        </div>
        <SelectField
          aria-label="Queue"
          value={filters.queue}
          onChange={(v) => onPatch({ queue: v })}
          size="compact"
          className="w-[8.75rem]"
          options={[
            { value: "all", label: "All queues" },
            ...queues.map((q) => ({ value: q, label: q })),
          ]}
        />
        <SelectField
          aria-label="Assignee"
          value={filters.assignee}
          onChange={(v) => onPatch({ assignee: v })}
          size="compact"
          className="w-[9.375rem]"
          options={[
            { value: "all", label: "All assignees" },
            ...assignees.map((a) => ({ value: a, label: a })),
          ]}
        />
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
          <Button variant="ghost" size="sm" className="h-400" onClick={onReset}>
            <X className="mr-050 h-3 w-3" /> Reset ({activeCount})
          </Button>
        )}
      </div>
      <div className="mt-100 flex flex-wrap items-center gap-075">
        <span className="text-body-small text-text-subtlest mr-050">Reason</span>
        {REASONS.map((r) => (
          <Chip
            key={r}
            on={filters.reasons.includes(r)}
            label={REASON_LABELS[r]}
            onClick={() => onPatch({ reasons: toggle(filters.reasons, r) })}
          />
        ))}
        <span className="text-body-small text-text-subtlest mx-100">Status</span>
        {STATUSES.map((s) => (
          <Chip
            key={s}
            on={filters.statuses.includes(s)}
            label={STATUS_LABELS[s]}
            onClick={() => onPatch({ statuses: toggle(filters.statuses, s) })}
          />
        ))}
        <span className="text-body-small text-text-subtlest mx-100">Reminder</span>
        {CHANNELS.map((c) => (
          <Chip
            key={c}
            on={filters.channels.includes(c)}
            label={CHANNEL_LABELS[c]}
            onClick={() => onPatch({ channels: toggle(filters.channels, c) })}
          />
        ))}
      </div>
    </div>
  );
}
