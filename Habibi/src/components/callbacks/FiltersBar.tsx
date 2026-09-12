import { SelectField } from "@/components/ui/select";
import { Chip } from "@/components/ui/chip";
import { FiltersBar as Bar, FilterGroup } from "@/components/records/FiltersBar";
import { toggleIn } from "@/lib/utils";
import type { CbChannel, CbReason, CbStatus, Filters } from "@/api/types/callbacks";
import { CHANNEL_LABELS, REASON_LABELS, STATUS_LABELS } from "@/lib/callbacks";

interface Props {
  filters: Filters;
  onPatch: (p: Partial<Filters>) => void;
  onReset: () => void;
  /** Real DB humans (+ Unassigned). */
  assignees: string[];
  /** Real DB teams. */
  queues: string[];
  myQueue: string;
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
    <Bar
      search={filters.search}
      onSearch={(search) => onPatch({ search })}
      placeholder="Search customer, account, ID…"
      activeCount={activeCount}
      onReset={onReset}
    >
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
        active={filters.myQueueOnly}
        onClick={() => onPatch({ myQueueOnly: !filters.myQueueOnly })}
      >
        My queue · {myQueue}
      </Chip>
      <Chip
        active={filters.dndSafeOnly}
        onClick={() => onPatch({ dndSafeOnly: !filters.dndSafeOnly })}
      >
        DND-safe only
      </Chip>

      <div className="flex basis-full flex-wrap items-center gap-100">
        <FilterGroup label="Reason">
          {REASONS.map((r) => (
            <Chip
              key={r}
              active={filters.reasons.includes(r)}
              onClick={() => onPatch({ reasons: toggleIn(filters.reasons, r) })}
            >
              {REASON_LABELS[r]}
            </Chip>
          ))}
        </FilterGroup>
        <FilterGroup label="Status">
          {STATUSES.map((s) => (
            <Chip
              key={s}
              active={filters.statuses.includes(s)}
              onClick={() => onPatch({ statuses: toggleIn(filters.statuses, s) })}
            >
              {STATUS_LABELS[s]}
            </Chip>
          ))}
        </FilterGroup>
        <FilterGroup label="Reminder">
          {CHANNELS.map((c) => (
            <Chip
              key={c}
              active={filters.channels.includes(c)}
              onClick={() => onPatch({ channels: toggleIn(filters.channels, c) })}
            >
              {CHANNEL_LABELS[c]}
            </Chip>
          ))}
        </FilterGroup>
      </div>
    </Bar>
  );
}
