import { useMemo } from "react";
import { Phone, Send, UserCog, Clock, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  fmtLongDate,
  REASON_LABELS,
  STATUS_LABELS,
  type Callback,
  type CbStatus,
} from "@/data/callbacks-seed";
import { FilterTable, type FilterChip, type FilterTableColumn } from "@/components/records/FilterTable";
import { cn } from "@/lib/utils";

interface Props {
  rows: Callback[];
  onOpen: (id: string) => void;
  onStart: (id: string) => void;
  onSendReminder: (id: string) => void;
  onReschedulePlus1h: (id: string) => void;
  onCancel: (id: string) => void;
}

/** Status order for chips — operational first, terminal last. */
const STATUS_ORDER: CbStatus[] = [
  "scheduled",
  "reminded",
  "in_progress",
  "missed",
  "completed",
  "rescheduled",
  "cancelled",
];

const STATUS_DOT: Record<CbStatus, string> = {
  scheduled: "var(--icon-accent-blue)",
  reminded: "var(--icon-accent-purple)",
  in_progress: "var(--icon-accent-teal)",
  completed: "var(--icon-accent-green)",
  missed: "var(--icon-accent-red)",
  rescheduled: "var(--icon-accent-orange)",
  cancelled: "var(--icon-accent-gray)",
};

const STATUS_PILL: Record<CbStatus, string> = {
  scheduled: "bg-background-accent-blue-subtlest text-text-accent-blue",
  reminded: "bg-background-accent-purple-subtlest text-text-accent-purple",
  in_progress: "bg-background-accent-teal-subtlest text-text-accent-teal",
  completed: "bg-background-accent-green-subtlest text-text-accent-green",
  missed: "bg-background-accent-red-subtlest text-text-accent-red",
  rescheduled: "bg-background-accent-orange-subtlest text-text-accent-orange",
  cancelled: "bg-background-accent-gray-subtlest text-text-accent-gray",
};

export function CallbackList({ rows, onOpen, onStart, onSendReminder, onReschedulePlus1h, onCancel }: Props) {
  const chips = useMemo<FilterChip<CbStatus>[]>(() => {
    const counts = new Map<CbStatus, number>();
    for (const row of rows) counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
    const present = STATUS_ORDER.filter((s) => (counts.get(s) ?? 0) > 0);
    // Always show the operational set even at 0 so empty states stay navigable.
    const keys: CbStatus[] =
      present.length > 0
        ? present
        : (["scheduled", "in_progress", "missed", "completed"] as CbStatus[]);
    return [
      { key: "all", label: "All", count: rows.length },
      ...keys.map((key) => ({
        key,
        label: STATUS_LABELS[key],
        dot: STATUS_DOT[key],
        count: counts.get(key) ?? 0,
      })),
    ];
  }, [rows]);

  const columns = useMemo<FilterTableColumn<Callback>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        width: "1.35fr",
        cell: (cb) => (
          <button type="button" onClick={() => onOpen(cb.id)} className="min-w-0 text-left">
            <span className="block truncate font-medium text-text hover:text-text-brand hover:underline">
              {cb.customerName}
            </span>
            <span className="block truncate text-body-small text-text-subtlest">
              ····{cb.accountTail} · {REASON_LABELS[cb.reason] ?? cb.reason}
            </span>
          </button>
        ),
      },
      {
        id: "when",
        header: "When",
        width: "0.95fr",
        cell: (cb) => (
          <div className="tabular-nums">
            <div className="text-text">{fmtLongDate(cb.scheduledAt)}</div>
            <div className="flex items-center gap-050 text-body-small text-text-subtlest">
              {cb.windowMins}m window
              {cb.dndActive ? (
                <>
                  <AlertTriangle className="h-3 w-3 text-text-warning" /> DND
                </>
              ) : null}
            </div>
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        width: "0.85fr",
        cell: (cb) => (
          <span
            className={cn(
              "inline-flex h-400 items-center rounded-small px-075 text-[0.6875rem] font-medium",
              STATUS_PILL[cb.status],
            )}
          >
            {STATUS_LABELS[cb.status]}
          </span>
        ),
      },
      {
        id: "assignee",
        header: "Assignee",
        width: "0.9fr",
        cell: (cb) => (
          <div className="min-w-0">
            <div className="truncate text-text">{cb.assignee || "Unassigned"}</div>
            <div className="truncate text-body-small text-text-subtlest">{cb.queue}</div>
          </div>
        ),
      },
      {
        id: "actions",
        header: "Actions",
        width: "1.1fr",
        className: "text-right",
        cell: (cb) => (
          <div className="inline-flex flex-wrap justify-end gap-050">
            {(cb.status === "scheduled" || cb.status === "reminded") && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-100 text-body-small"
                onClick={() => onStart(cb.id)}
              >
                <Phone className="mr-050 h-3 w-3" /> Start
              </Button>
            )}
            {(cb.status === "scheduled" || cb.status === "reminded") && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-100 text-body-small"
                onClick={() => onSendReminder(cb.id)}
              >
                <Send className="mr-050 h-3 w-3" /> Remind
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-100 text-body-small"
              onClick={() => onReschedulePlus1h(cb.id)}
            >
              <Clock className="mr-050 h-3 w-3" /> +1h
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0"
              title="Open detail"
              onClick={() => onOpen(cb.id)}
            >
              <UserCog className="h-3.5 w-3.5" />
            </Button>
            {cb.status !== "completed" && cb.status !== "cancelled" && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0 text-text-danger"
                title="Cancel"
                onClick={() => onCancel(cb.id)}
              >
                <XCircle className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        ),
      },
    ],
    [onOpen, onStart, onSendReminder, onReschedulePlus1h, onCancel],
  );

  return (
    <FilterTable
      rows={rows}
      getRowId={(cb) => cb.id}
      getStatus={(cb) => cb.status}
      chips={chips}
      columns={columns}
      emptyMessage="No callbacks match this status."
      ariaLabel="Scrollable callbacks table"
      className="min-h-0 flex-1"
      defaultFilter="all"
    />
  );
}
