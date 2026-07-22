import { Phone, Send, UserCog, Clock, XCircle, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { fmtLongDate, REASON_LABELS, STATUS_TONE, STATUS_LABELS, type Callback } from "@/data/callbacks-seed";

interface Props {
  rows: Callback[];
  onOpen: (id: string) => void;
  onStart: (id: string) => void;
  onSendReminder: (id: string) => void;
  onReschedulePlus1h: (id: string) => void;
  onCancel: (id: string) => void;
}

export function CallbackList({ rows, onOpen, onStart, onSendReminder, onReschedulePlus1h, onCancel }: Props) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-[var(--border-token)] bg-surface-card">
      <table className="w-full text-[12px]">
        <thead className="sticky top-0 z-10 bg-surface-sunken/70 backdrop-blur">
          <tr className="text-left text-[10.5px] uppercase tracking-wide text-text-muted">
            <th className="px-3 py-2 font-semibold">Customer</th>
            <th className="px-2 py-2 font-semibold">When</th>
            <th className="px-2 py-2 font-semibold">Reason</th>
            <th className="px-2 py-2 font-semibold">Queue / Assignee</th>
            <th className="px-2 py-2 font-semibold">Status</th>
            <th className="px-3 py-2 font-semibold text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-10 text-center text-text-muted">No callbacks match these filters.</td>
            </tr>
          )}
          {rows.map((cb) => (
            <tr key={cb.id} className="border-t border-[var(--border-token)] hover:bg-surface-sunken/40">
              <td className="px-3 py-2">
                <button onClick={() => onOpen(cb.id)} className="text-left">
                  <div className="font-medium text-brand-navy">{cb.customerName}</div>
                  <div className="text-[10.5px] text-text-muted">····{cb.accountTail} · {cb.id}</div>
                </button>
              </td>
              <td className="px-2 py-2 tabular-nums">
                <div className="text-text-primary">{fmtLongDate(cb.scheduledAt)}</div>
                <div className="text-[10.5px] text-text-muted flex items-center gap-1">
                  {cb.windowMins}m window
                  {cb.dndActive && <><AlertTriangle className="h-3 w-3 text-amber-600" /> DND</>}
                </div>
              </td>
              <td className="px-2 py-2 text-text-secondary">{REASON_LABELS[cb.reason]}</td>
              <td className="px-2 py-2">
                <div className="text-text-primary">{cb.queue}</div>
                <div className="text-[10.5px] text-text-muted">{cb.assignee}</div>
              </td>
              <td className="px-2 py-2">
                <span className={cn("inline-flex rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold", STATUS_TONE[cb.status])}>
                  {STATUS_LABELS[cb.status]}
                </span>
              </td>
              <td className="px-3 py-2 text-right">
                <div className="inline-flex gap-1">
                  {(cb.status === "scheduled" || cb.status === "reminded") && (
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={() => onStart(cb.id)}>
                      <Phone className="mr-1 h-3 w-3" /> Start
                    </Button>
                  )}
                  {(cb.status === "scheduled" || cb.status === "reminded") && (
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={() => onSendReminder(cb.id)}>
                      <Send className="mr-1 h-3 w-3" /> Remind
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={() => onReschedulePlus1h(cb.id)}>
                    <Clock className="mr-1 h-3 w-3" /> +1h
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0" title="Open detail" onClick={() => onOpen(cb.id)}>
                    <UserCog className="h-3.5 w-3.5" />
                  </Button>
                  {cb.status !== "completed" && cb.status !== "cancelled" && (
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-red-600" title="Cancel" onClick={() => onCancel(cb.id)}>
                      <XCircle className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
