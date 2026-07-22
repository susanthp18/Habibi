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
  const tone = c === "whatsapp" ? "text-emerald-600" : c === "email" ? "text-brand-primary" : "text-amber-600";
  return <I className={cn("h-3.5 w-3.5", tone)} />;
}

const AGING_TONE = {
  fresh: "bg-emerald-50 text-emerald-700",
  warn: "bg-amber-50 text-amber-800",
  stale: "bg-red-50 text-red-700",
  done: "bg-surface-sunken text-text-muted",
};

export function RequestsTable({ rows, selected, onToggle, onToggleAll, onOpen, onGenerate, onRetry }: Props) {
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  return (
    <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="h-full overflow-auto">
        <table className="w-full min-w-[900px] text-[12px]">
          <thead className="sticky top-0 z-10 bg-surface-sunken/80 backdrop-blur">
            <tr className="text-left text-[10.5px] uppercase tracking-wide text-text-muted">
              <th className="w-8 px-2 py-2">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => onToggleAll(rows.map((r) => r.id))}
                  aria-label="Select all"
                />
              </th>
              <th className="px-2 py-2">Customer</th>
              <th className="px-2 py-2">Document</th>
              <th className="px-2 py-2">Via</th>
              <th className="px-2 py-2">Channel</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Aging</th>
              <th className="px-2 py-2">Assignee</th>
              <th className="px-2 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-16 text-center text-[12px] text-text-muted">
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
                    "border-t border-[var(--border-token)] hover:bg-surface-sunken/50 cursor-pointer",
                    selected.has(d.id) && "bg-brand-tint/40",
                  )}
                  onClick={() => onOpen(d)}
                >
                  <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(d.id)}
                      onChange={() => onToggle(d.id)}
                      aria-label={`Select ${d.id}`}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <Link
                      to="/customers/$customerId"
                      params={{ customerId: d.customerId }}
                      onClick={(e) => e.stopPropagation()}
                      className="font-semibold text-brand-navy hover:underline"
                    >
                      {d.customerName}
                    </Link>
                    <div className="text-[10.5px] text-text-muted">
                      #{d.accountTail} · {d.id}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="font-medium text-brand-navy">{DOC_TYPE_LABELS[d.docType]}</div>
                    {d.period && <div className="text-[10.5px] text-text-muted">{d.period}</div>}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1 text-text-secondary">
                      {d.requestedVia === "agent" ? (
                        <User className="h-3.5 w-3.5" />
                      ) : (
                        <>
                          <Bot className="h-3.5 w-3.5" />
                          {d.requestedVia === "bot_voice" ? <Mic className="h-3 w-3" /> : null}
                        </>
                      )}
                      <span className="text-[11px]">
                        {d.requestedVia === "bot_voice" ? "Voice" : d.requestedVia === "bot_chat" ? "Chat" : "Agent"}
                      </span>
                    </div>
                    <div className="text-[10.5px] text-text-muted">{fmtDate(d.requestedAt, { timeStyle: "short", dateStyle: "short" })}</div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1">
                      <ChannelIcon c={d.deliveryChannel} />
                      <span className="text-[11.5px] text-text-secondary">{CHANNEL_LABELS[d.deliveryChannel]}</span>
                    </div>
                    <div className="truncate text-[10.5px] text-text-muted max-w-[180px]">{d.deliveryTarget}</div>
                  </td>
                  <td className="px-2 py-2">
                    <StatusPill status={d.status} />
                    {d.status === "failed" && d.failedReason && (
                      <div className="mt-0.5 truncate text-[10.5px] text-red-600 max-w-[180px]" title={d.failedReason}>
                        {d.failedReason}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium tabular-nums", AGING_TONE[aging.tone])}>
                      {aging.label}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-[11.5px] text-text-secondary">{d.assignee}</td>
                  <td className="px-2 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="inline-flex items-center gap-1">
                      {d.status === "requested" && (
                        <Button size="sm" className="h-7 px-2 text-[11px]" onClick={() => onGenerate(d)}>
                          <Send className="mr-1 h-3 w-3" /> Generate
                        </Button>
                      )}
                      {d.status === "failed" && (
                        <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => onRetry(d)}>
                          <RotateCw className="mr-1 h-3 w-3" /> Retry
                        </Button>
                      )}
                      {d.status === "sent" && (
                        <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => onGenerate(d)}>
                          <RotateCw className="mr-1 h-3 w-3" /> Resend
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
