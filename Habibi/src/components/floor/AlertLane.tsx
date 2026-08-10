import { AlertTriangle, ChevronRight, Headphones, PhoneForwarded } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActiveCall, FloorAlert } from "@/data/floor-seed";
import { Badge } from "@/components/ui/badge";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  alerts: FloorAlert[];
  calls: ActiveCall[];
  onFocus: (callId: string) => void;
  onListen: (callId: string) => void;
  onBarge: (callId: string) => void;
  compact?: boolean;
};

const sevCls: Record<1 | 2 | 3, string> = {
  3: "border-l-[var(--sentiment-negative)] bg-background-danger/40",
  2: "border-l-[var(--sentiment-neutral)] bg-background-warning/40",
  1: "border-l-[var(--border)] bg-surface-sunken",
};

export function AlertLane({ alerts, calls, onFocus, onListen, onBarge, compact }: Props) {
  const list = compact ? alerts.slice(0, 2) : alerts;

  return (
    <aside
      className={cn(
        "flex flex-col overflow-hidden bg-surface",
        compact
          ? "shrink-0 border-b border-border"
          : "hidden w-[20rem] shrink-0 border-l border-border xl:flex",
      )}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-border px-150 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <AlertTriangle className="h-3.5 w-3.5 text-text-danger" />
          Calls turning negative
        </div>
        <Badge variant="destructive" className="tabular">
          {alerts.length}
        </Badge>
      </div>

      <div className={cn("min-h-0 flex-1 overflow-y-auto", compact && "max-h-[8.75rem]")}>
        {list.length === 0 && (
          <div className="p-300 text-center text-body-small text-text-subtlest">
            No calls flagged. Floor is calm.
          </div>
        )}
        <ul className="divide-y divide-border">
          {list.map((a) => {
            const call = calls.find((c) => c.id === a.callId);
            if (!call) return null;
            return (
              <li key={a.id} className={cn("border-l-4 px-150 py-150", sevCls[a.severity])}>
                <button
                  type="button"
                  onClick={() => onFocus(a.callId)}
                  className="group flex w-full items-start justify-between text-left"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-075">
                      <span className="truncate text-body-small font-semibold text-text">
                        {call.customer}
                      </span>
                      <Lozenge tone="neutral">
                        {call.handler.kind === "human" ? call.handler.name : "Bot"}
                      </Lozenge>
                    </div>
                    <p className="mt-025 line-clamp-2 text-body-small text-text-subtle">
                      {a.reason}
                    </p>
                    <span className="tabular text-body-small text-text-subtlest">{a.at}</span>
                  </div>
                  <ChevronRight className="mt-025 h-3.5 w-3.5 shrink-0 text-text-subtlest group-hover:text-text-brand" />
                </button>
                <div className="mt-075 flex gap-050">
                  <button
                    type="button"
                    onClick={() => onListen(a.callId)}
                    className="flex flex-1 items-center justify-center gap-050 rounded-medium border border-border bg-surface px-100 py-050 text-body-small font-medium text-text-subtle hover:bg-surface-sunken"
                  >
                    <Headphones className="h-3 w-3" />
                    Listen
                  </button>
                  <button
                    type="button"
                    onClick={() => onBarge(a.callId)}
                    className="flex flex-1 items-center justify-center gap-050 rounded-medium bg-background-danger-bold px-100 py-050 text-body-small font-semibold text-white hover:bg-background-danger-bold-hovered"
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
