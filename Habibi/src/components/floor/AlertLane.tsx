import { AlertTriangle, ChevronRight, Headphones, PhoneForwarded } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActiveCall, FloorAlert } from "@/data/floor-seed";

type Props = {
  alerts: FloorAlert[];
  calls: ActiveCall[];
  onFocus: (callId: string) => void;
  onListen: (callId: string) => void;
  onBarge: (callId: string) => void;
  compact?: boolean;
};

const sevCls: Record<1 | 2 | 3, string> = {
  3: "border-l-[var(--sentiment-negative)] bg-danger-bg/40",
  2: "border-l-[var(--sentiment-neutral)] bg-warning-bg/40",
  1: "border-l-[var(--border-token)] bg-surface-sunken",
};

export function AlertLane({ alerts, calls, onFocus, onListen, onBarge, compact }: Props) {
  const list = compact ? alerts.slice(0, 2) : alerts;

  return (
    <aside
      className={cn(
        "flex flex-col overflow-hidden bg-surface-card",
        compact
          ? "shrink-0 border-b border-[var(--border-token)]"
          : "hidden w-[320px] shrink-0 border-l border-[var(--border-token)] xl:flex",
      )}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-brand-navy">
          <AlertTriangle className="h-3.5 w-3.5 text-danger" />
          Calls turning negative
        </div>
        <span className="tabular rounded-full bg-danger-bg px-1.5 py-0.5 text-[10px] font-semibold text-danger">
          {alerts.length}
        </span>
      </div>

      <div className={cn("min-h-0 flex-1 overflow-y-auto", compact && "max-h-[140px]")}>
        {list.length === 0 && (
          <div className="p-6 text-center text-[11px] text-text-muted">
            No calls flagged. Floor is calm.
          </div>
        )}
        <ul className="divide-y divide-[var(--border-token)]">
          {list.map((a) => {
            const call = calls.find((c) => c.id === a.callId);
            if (!call) return null;
            return (
              <li key={a.id} className={cn("border-l-4 px-3 py-2.5", sevCls[a.severity])}>
                <button
                  type="button"
                  onClick={() => onFocus(a.callId)}
                  className="group flex w-full items-start justify-between text-left"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-[12px] font-semibold text-brand-navy">
                        {call.customer}
                      </span>
                      <span className="rounded-full bg-surface-card px-1 py-0.5 text-[9px] text-text-secondary">
                        {call.handler.kind === "human" ? call.handler.name : "Bot"}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[11px] text-text-secondary">
                      {a.reason}
                    </p>
                    <span className="tabular text-[10px] text-text-muted">{a.at}</span>
                  </div>
                  <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-muted group-hover:text-brand-primary" />
                </button>
                <div className="mt-1.5 flex gap-1">
                  <button
                    type="button"
                    onClick={() => onListen(a.callId)}
                    className="flex flex-1 items-center justify-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[10px] font-medium text-text-secondary hover:bg-surface-sunken"
                  >
                    <Headphones className="h-3 w-3" />
                    Listen
                  </button>
                  <button
                    type="button"
                    onClick={() => onBarge(a.callId)}
                    className="flex flex-1 items-center justify-center gap-1 rounded-md bg-danger px-2 py-1 text-[10px] font-semibold text-white hover:bg-[#b3271d]"
                  >
                    <PhoneForwarded className="h-3 w-3" />
                    Barge
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
