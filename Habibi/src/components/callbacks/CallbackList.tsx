import { Phone, Send, UserCog, Clock, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtLongDate, REASON_LABELS, STATUS_TONE, STATUS_LABELS, type Callback } from "@/data/callbacks-seed";
import { Lozenge } from "@/components/ui/lozenge";

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
    <div className="min-h-0 flex-1 overflow-y-auto rounded-large border border-border bg-surface">
      <table className="w-full text-body-small">
        <thead className="sticky top-0 z-10 bg-surface-sunken/70 backdrop-blur">
          <tr className="text-left text-body-small text-text-subtlest">
            <th className="px-150 py-100 font-semibold">Customer</th>
            <th className="px-100 py-100 font-semibold">When</th>
            <th className="px-100 py-100 font-semibold">Reason</th>
            <th className="px-100 py-100 font-semibold">Queue / Assignee</th>
            <th className="px-100 py-100 font-semibold">Status</th>
            <th className="px-150 py-100 font-semibold text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="px-150 py-500 text-center text-text-subtlest">No callbacks match these filters.</td>
            </tr>
          )}
          {rows.map((cb) => (
            <tr key={cb.id} className="border-t border-border hover:bg-surface-sunken/40">
              <td className="px-150 py-100">
                <button onClick={() => onOpen(cb.id)} className="text-left">
                  <div className="font-medium text-text">{cb.customerName}</div>
                  <div className="text-body-small text-text-subtlest">····{cb.accountTail} · {cb.id}</div>
                </button>
              </td>
              <td className="px-100 py-100 tabular-nums">
                <div className="text-text">{fmtLongDate(cb.scheduledAt)}</div>
                <div className="text-body-small text-text-subtlest flex items-center gap-050">
                  {cb.windowMins}m window
                  {cb.dndActive && <><AlertTriangle className="h-3 w-3 text-text-warning" /> DND</>}
                </div>
              </td>
              <td className="px-100 py-100 text-text-subtle">{REASON_LABELS[cb.reason]}</td>
              <td className="px-100 py-100">
                <div className="text-text">{cb.queue}</div>
                <div className="text-body-small text-text-subtlest">{cb.assignee}</div>
              </td>
              <td className="px-100 py-100">
                <Lozenge tone={STATUS_TONE[cb.status]}>
                  {STATUS_LABELS[cb.status]}
                </Lozenge>
              </td>
              <td className="px-150 py-100 text-right">
                <div className="inline-flex gap-050">
                  {(cb.status === "scheduled" || cb.status === "reminded") && (
                    <Button size="sm" variant="ghost" className="h-7 px-100 text-body-small" onClick={() => onStart(cb.id)}>
                      <Phone className="mr-050 h-3 w-3" /> Start
                    </Button>
                  )}
                  {(cb.status === "scheduled" || cb.status === "reminded") && (
                    <Button size="sm" variant="ghost" className="h-7 px-100 text-body-small" onClick={() => onSendReminder(cb.id)}>
                      <Send className="mr-050 h-3 w-3" /> Remind
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="h-7 px-100 text-body-small" onClick={() => onReschedulePlus1h(cb.id)}>
                    <Clock className="mr-050 h-3 w-3" /> +1h
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0" title="Open detail" onClick={() => onOpen(cb.id)}>
                    <UserCog className="h-3.5 w-3.5" />
                  </Button>
                  {cb.status !== "completed" && cb.status !== "cancelled" && (
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-text-danger" title="Cancel" onClick={() => onCancel(cb.id)}>
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
