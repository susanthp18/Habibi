import { PhoneOff, RefreshCw, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtLongDate, REASON_LABELS, type Callback } from "@/data/callbacks-seed";

interface Props {
  rows: Callback[];
  onOpen: (id: string) => void;
  onRetry: (id: string) => void;
  onReschedulePlus1h: (id: string) => void;
  onReschedulePlus1d: (id: string) => void;
}

export function MissedLane({ rows, onOpen, onRetry, onReschedulePlus1h, onReschedulePlus1d }: Props) {
  if (rows.length === 0) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center rounded-lg border border-dashed border-[var(--border-token)] bg-surface-card p-8 text-center">
        <div>
          <PhoneOff className="mx-auto mb-2 h-6 w-6 text-emerald-500" />
          <div className="text-[13px] font-semibold text-brand-navy">No missed callbacks — nicely done.</div>
          <div className="text-[11px] text-text-muted">Missed items will surface here for one-click recovery.</div>
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-red-200 bg-red-50/40">
      <div className="sticky top-0 border-b border-red-200 bg-red-50/80 px-3 py-1.5 text-[11px] font-semibold text-red-800 backdrop-blur">
        {rows.length} missed callback{rows.length === 1 ? "" : "s"} · recover now
      </div>
      <ul className="divide-y divide-red-100">
        {rows.map((cb) => (
          <li key={cb.id} className="flex items-center gap-2 px-3 py-2 hover:bg-red-50">
            <PhoneOff className="h-4 w-4 shrink-0 text-red-600" />
            <button onClick={() => onOpen(cb.id)} className="min-w-0 flex-1 text-left">
              <div className="truncate text-[12.5px] font-medium text-brand-navy">{cb.customerName} · <span className="text-text-muted">····{cb.accountTail}</span></div>
              <div className="truncate text-[10.5px] text-text-muted">
                Missed {fmtLongDate(cb.scheduledAt)} · {REASON_LABELS[cb.reason]} · {cb.assignee}
              </div>
            </button>
            <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => onRetry(cb.id)}>
              <RefreshCw className="mr-1 h-3 w-3" /> Retry now
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={() => onReschedulePlus1h(cb.id)}>
              <Clock className="mr-1 h-3 w-3" /> +1h
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={() => onReschedulePlus1d(cb.id)}>
              +1d
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
