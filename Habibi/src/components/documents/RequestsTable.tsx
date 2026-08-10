import { Link } from "@tanstack/react-router";
import { Mail, MessageCircle, Smartphone, Bot, User, Mic, Send, RotateCw, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  DOC_TYPE_LABELS,
  agingInfo,
  fmtDate,
  type DocChannel,
  type DocRequest,
} from "@/data/documents-seed";
import { StatusPill } from "./StatusPill";

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

const AGING_TONE = {
  fresh: "bg-background-success-subtler text-text-success-bolder",
  warn: "bg-background-warning-subtler text-text-warning-bolder",
  stale: "bg-background-danger-subtler text-text-danger-bolder",
  done: "bg-surface-sunken text-text-subtlest",
};

export function RequestsTable({ rows, selected, onToggle, onToggleAll, onOpen, onGenerate, onRetry }: Props) {
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  return (
    <div className="min-h-0 flex-1 overflow-hidden rounded-large border border-border bg-surface">
      <div className="h-full overflow-auto">
        <table className="w-full min-w-[56.25rem] text-body-small">
          <thead className="sticky top-0 z-10 bg-surface-sunken/80 backdrop-blur">
            <tr className="text-left text-body-small text-text-subtlest">
              <th className="w-400 px-100 py-100">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => onToggleAll(rows.map((r) => r.id))}
                  aria-label="Select all"
                />
              </th>
              <th className="px-100 py-100">Customer</th>
              <th className="px-100 py-100">Document</th>
              <th className="px-100 py-100">Via</th>
              <th className="px-100 py-100">Channel</th>
              <th className="px-100 py-100">Status</th>
              <th className="px-100 py-100">Aging</th>
              <th className="px-100 py-100">Assignee</th>
              <th className="px-100 py-100 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-200 py-800 text-center text-body-small text-text-subtlest">
                  No requests match the current filters.
                </td>
              </tr>
            )}
            {rows.map((d) => {
              const aging = agingInfo(d);
              return (
                <tr
                  key={d.id}
                  className={cn(
                    "border-t border-border hover:bg-surface-sunken/50 cursor-pointer",
                    selected.has(d.id) && "bg-background-brand-subtlest/40",
                  )}
                  onClick={() => onOpen(d)}
                >
                  <td className="px-100 py-100" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(d.id)}
                      onChange={() => onToggle(d.id)}
                      aria-label={`Select ${d.id}`}
                    />
                  </td>
                  <td className="px-100 py-100">
                    <Link
                      to="/customers/$customerId"
                      params={{ customerId: d.customerId }}
                      onClick={(e) => e.stopPropagation()}
                      className="font-semibold text-text hover:underline"
                    >
                      {d.customerName}
                    </Link>
                    <div className="text-body-small text-text-subtlest">
                      #{d.accountTail} · {d.id}
                    </div>
                  </td>
                  <td className="px-100 py-100">
                    <div className="font-medium text-text">{DOC_TYPE_LABELS[d.docType]}</div>
                    {d.period && <div className="text-body-small text-text-subtlest">{d.period}</div>}
                  </td>
                  <td className="px-100 py-100">
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
                        {d.requestedVia === "bot_voice" ? "Voice" : d.requestedVia === "bot_chat" ? "Chat" : "Agent"}
                      </span>
                    </div>
                    <div className="text-body-small text-text-subtlest">{fmtDate(d.requestedAt, { timeStyle: "short", dateStyle: "short" })}</div>
                  </td>
                  <td className="px-100 py-100">
                    <div className="flex items-center gap-050">
                      <ChannelIcon c={d.deliveryChannel} />
                      <span className="text-body-small text-text-subtle">{CHANNEL_LABELS[d.deliveryChannel]}</span>
                    </div>
                    <div className="truncate text-body-small text-text-subtlest max-w-[11.25rem]">{d.deliveryTarget}</div>
                  </td>
                  <td className="px-100 py-100">
                    <StatusPill status={d.status} />
                    {d.status === "failed" && d.failedReason && (
                      <div className="mt-025 truncate text-body-small text-text-danger max-w-[11.25rem]" title={d.failedReason}>
                        {d.failedReason}
                      </div>
                    )}
                  </td>
                  <td className="px-100 py-100">
                    <span className={cn("rounded px-075 py-025 text-body-small font-medium tabular-nums", AGING_TONE[aging.tone])}>
                      {aging.label}
                    </span>
                  </td>
                  <td className="px-100 py-100 text-body-small text-text-subtle">{d.assignee}</td>
                  <td className="px-100 py-100 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="inline-flex items-center gap-050">
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
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
