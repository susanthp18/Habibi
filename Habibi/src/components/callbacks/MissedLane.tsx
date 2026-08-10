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
      <div className="grid min-h-0 flex-1 place-items-center rounded-large border border-dashed border-border bg-surface p-400 text-center">
        <div>
          <PhoneOff className="mx-auto mb-100 h-300 w-300 text-text-success" />
          <div className="text-body font-semibold text-text">No missed callbacks — nicely done.</div>
          <div className="text-body-small text-text-subtlest">Missed items will surface here for one-click recovery.</div>
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto rounded-large border border-border-danger-subtle bg-background-danger-subtler/40">
      <div className="sticky top-0 border-b border-border-danger-subtle bg-background-danger-subtler/80 px-150 py-075 text-body-small font-semibold text-text-danger-bolder backdrop-blur">
        {rows.length} missed callback{rows.length === 1 ? "" : "s"} · recover now
      </div>
      <ul className="divide-y divide-red-100">
        {rows.map((cb) => (
          <li key={cb.id} className="flex items-center gap-100 px-150 py-100 hover:bg-background-danger-subtler">
            <PhoneOff className="h-4 w-4 shrink-0 text-text-danger" />
            <button onClick={() => onOpen(cb.id)} className="min-w-0 flex-1 text-left">
              <div className="truncate text-[0.75rem] font-medium text-text">{cb.customerName} · <span className="text-text-subtlest">····{cb.accountTail}</span></div>
              <div className="truncate text-body-small text-text-subtlest">
                Missed {fmtLongDate(cb.scheduledAt)} · {REASON_LABELS[cb.reason]} · {cb.assignee}
              </div>
            </button>
            <Button size="sm" variant="outline" className="h-7 text-body-small" onClick={() => onRetry(cb.id)}>
              <RefreshCw className="mr-050 h-3 w-3" /> Retry now
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-body-small" onClick={() => onReschedulePlus1h(cb.id)}>
              <Clock className="mr-050 h-3 w-3" /> +1h
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-body-small" onClick={() => onReschedulePlus1d(cb.id)}>
              +1d
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
