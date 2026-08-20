import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Mail, MessageCircle, Smartphone, Bot, User, Mic, Send, RotateCw, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  DOC_TYPE_LABELS,
  STATUS_LABELS,
  STATUS_ORDER,
  agingInfo,
  fmtDate,
  type DocChannel,
  type DocRequest,
  type DocStatus,
} from "@/data/documents-seed";
import { FilterTable, type FilterChip, type FilterTableColumn } from "@/components/records/FilterTable";

interface Props {
  rows: DocRequest[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[]) => void;
  onOpen: (d: DocRequest) => void;
  onGenerate: (d: DocRequest) => void;
  onRetry: (d: DocRequest) => void;
}

function ChannelIcon({ c }: { c: DocChannel }) {
  const I = c === "whatsapp" ? MessageCircle : c === "email" ? Mail : Smartphone;
  const tone = c === "whatsapp" ? "text-text-success" : c === "email" ? "text-text-brand" : "text-text-warning";
  return <I className={cn("h-3.5 w-3.5", tone)} />;
}

const STATUS_DOT: Record<DocStatus, string> = {
  requested: "var(--icon-accent-orange)",
  generating: "var(--icon-accent-teal)",
  sent: "var(--icon-accent-green)",
  failed: "var(--icon-accent-red)",
};

const STATUS_PILL: Record<DocStatus, string> = {
  requested: "bg-background-accent-orange-subtlest text-text-accent-orange",
  generating: "bg-background-accent-teal-subtlest text-text-accent-teal",
  sent: "bg-background-accent-green-subtlest text-text-accent-green",
  failed: "bg-background-accent-red-subtlest text-text-accent-red",
};

const AGING_TONE = {
  fresh: "bg-background-success-subtler text-text-success-bolder",
  warn: "bg-background-warning-subtler text-text-warning-bolder",
  stale: "bg-background-danger-subtler text-text-danger-bolder",
  done: "bg-surface-sunken text-text-subtlest",
};

export function RequestsTable({ rows, selected, onToggle, onToggleAll, onOpen, onGenerate, onRetry }: Props) {
  const [statusFilter, setStatusFilter] = useState<DocStatus | "all">("all");

  const visibleIds = useMemo(() => {
    return rows
      .filter((d) => statusFilter === "all" || d.status === statusFilter)
      .map((d) => d.id);
  }, [rows, statusFilter]);

  const chips = useMemo<FilterChip<DocStatus>[]>(() => {
    const counts = new Map<DocStatus, number>();
    for (const row of rows) counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
    return [
      { key: "all", label: "All", count: rows.length },
      ...STATUS_ORDER.map((key) => ({
        key,
        label: STATUS_LABELS[key],
        dot: STATUS_DOT[key],
        count: counts.get(key) ?? 0,
      })),
    ];
  }, [rows]);

  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const someVisibleSelected = visibleIds.some((id) => selected.has(id));

  const columns = useMemo<FilterTableColumn<DocRequest>[]>(
    () => [
      {
        id: "select",
        header: "",
        width: "2.5rem",
        cell: (d) => (
          <span onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={selected.has(d.id)}
              onCheckedChange={() => onToggle(d.id)}
              aria-label={`Select ${d.id}`}
            />
          </span>
        ),
      },
      {
        id: "customer",
        header: "Customer",
        width: "1.25fr",
        cell: (d) => (
          <div className="min-w-0">
            <Link
              to="/customers/$customerId"
              params={{ customerId: d.customerId }}
              onClick={(e) => e.stopPropagation()}
              className="block truncate font-semibold text-text hover:text-text-brand hover:underline"
            >
              {d.customerName}
            </Link>
            <div className="truncate text-body-small text-text-subtlest">
              #{d.accountTail} · {d.id}
            </div>
          </div>
        ),
      },
      {
        id: "document",
        header: "Document",
        width: "1.15fr",
        cell: (d) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-text">{DOC_TYPE_LABELS[d.docType] ?? d.docType}</div>
            {d.period ? <div className="truncate text-body-small text-text-subtlest">{d.period}</div> : null}
          </div>
        ),
      },
      {
        id: "via",
        header: "Via",
        width: "0.7fr",
        cell: (d) => (
          <div>
            <div className="flex items-center gap-050 text-text-subtle">
              {d.requestedVia === "agent" ? (
                <User className="h-3.5 w-3.5" />
              ) : (
                <>
                  <Bot className="h-3.5 w-3.5" />
                  {d.requestedVia === "bot_voice" ? <Mic className="h-3 w-3" /> : null}
                </>
              )}
              <span className="text-body-small">
                {d.requestedVia === "bot_voice"
                  ? "Voice"
                  : d.requestedVia === "bot_chat"
                    ? "Chat"
                    : d.requestedVia === "vision" || d.requestedVia === "inbox"
                      ? "Vision"
                      : d.requestedVia === "clerk"
                        ? "Clerk"
                        : d.requestedVia === "mcp"
                          ? "MCP"
                          : "Agent"}
              </span>
            </div>
            {d.source && d.source !== "crm" ? (
              <div className="text-body-small text-text-subtlest">source: {d.source}</div>
            ) : null}
            <div className="text-body-small text-text-subtlest">
              {fmtDate(d.requestedAt, { timeStyle: "short", dateStyle: "short" })}
            </div>
          </div>
        ),
      },
      {
        id: "channel",
        header: "Channel",
        width: "0.85fr",
        cell: (d) => (
          <div className="min-w-0">
            <div className="flex items-center gap-050">
              <ChannelIcon c={d.deliveryChannel} />
              <span className="text-body-small text-text-subtle">
                {CHANNEL_LABELS[d.deliveryChannel] ?? d.deliveryChannel}
              </span>
            </div>
            <div className="truncate text-body-small text-text-subtlest">{d.deliveryTarget}</div>
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        width: "0.85fr",
        cell: (d) => (
          <div>
            <span
              className={cn(
                "inline-flex h-400 items-center rounded-small px-075 text-[0.6875rem] font-medium",
                STATUS_PILL[d.status],
              )}
            >
              {STATUS_LABELS[d.status]}
            </span>
            {d.status === "failed" && d.failedReason ? (
              <div className="mt-025 truncate text-body-small text-text-danger" title={d.failedReason}>
                {d.failedReason}
              </div>
            ) : null}
          </div>
        ),
      },
      {
        id: "aging",
        header: "Aging",
        width: "0.55fr",
        cell: (d) => {
          const aging = agingInfo(d);
          return (
            <span className={cn("rounded px-075 py-025 text-body-small font-medium tabular-nums", AGING_TONE[aging.tone])}>
              {aging.label}
            </span>
          );
        },
      },
      {
        id: "assignee",
        header: "Assignee",
        width: "0.75fr",
        cell: (d) => <span className="truncate text-body-small text-text-subtle">{d.assignee || "Unassigned"}</span>,
      },
      {
        id: "actions",
        header: "Actions",
        width: "1fr",
        className: "text-right",
        cell: (d) => (
          <div className="inline-flex items-center justify-end gap-050" onClick={(e) => e.stopPropagation()}>
            {d.status === "requested" && (
              <Button size="sm" className="h-7 px-100 text-body-small" onClick={() => onGenerate(d)}>
                <Send className="mr-050 h-3 w-3" /> Generate
              </Button>
            )}
            {d.status === "failed" && (
              <Button size="sm" variant="outline" className="h-7 px-100 text-body-small" onClick={() => onRetry(d)}>
                <RotateCw className="mr-050 h-3 w-3" /> Retry
              </Button>
            )}
            {d.status === "sent" && (
              <Button size="sm" variant="outline" className="h-7 px-100 text-body-small" onClick={() => onGenerate(d)}>
                <RotateCw className="mr-050 h-3 w-3" /> Resend
              </Button>
            )}
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onOpen(d)} aria-label="Open">
              <MoreHorizontal className="h-3.5 w-3.5" />
            </Button>
          </div>
        ),
      },
    ],
    [selected, onToggle, onOpen, onGenerate, onRetry],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-100">
      <div className="flex items-center gap-100 px-025">
        <Checkbox
          checked={allVisibleSelected ? true : someVisibleSelected ? "indeterminate" : false}
          onCheckedChange={() => onToggleAll(visibleIds)}
          aria-label="Select all visible requests"
        />
        <span className="text-body-small text-text-subtlest">
          {selected.size > 0 ? `${selected.size} selected` : "Select rows for bulk actions"}
        </span>
      </div>
      <FilterTable
        rows={rows}
        getRowId={(d) => d.id}
        getStatus={(d) => d.status}
        chips={chips}
        columns={columns}
        filter={statusFilter}
        onFilterChange={setStatusFilter}
        emptyMessage="No requests match this status."
        ariaLabel="Document requests table"
        className="min-h-0 flex-1"
      />
    </div>
  );
}
