import {
  AlertTriangle,
  Headphones,
  MessageSquare,
  PhoneForwarded,
  LayoutGrid,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { actionLabel, type ActiveCall, type FloorAction, type FloorAlert } from "@/data/floor-seed";
import { Badge } from "@/components/ui/badge";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  alerts: FloorAlert[];
  calls: ActiveCall[];
  onFocus: (callId: string) => void;
  onAction: (callId: string, action: FloorAction) => void;
  onAck: (alertId: string) => void;
};

const sevCls: Record<1 | 2 | 3, string> = {
  3: "border-l-[var(--sentiment-negative)] bg-background-danger/40",
  2: "border-l-[var(--sentiment-neutral)] bg-background-warning/40",
  1: "border-l-[var(--border)] bg-surface-sunken",
};

const ActionIcon = ({ action }: { action: FloorAction }) => {
  if (action === "barge") return <PhoneForwarded className="h-3 w-3" />;
  if (action === "whisper") return <MessageSquare className="h-3 w-3" />;
  if (action === "inbox") return <LayoutGrid className="h-3 w-3" />;
  return <Headphones className="h-3 w-3" />;
};

export function PriorityLane({ alerts, calls, onFocus, onAction, onAck }: Props) {
  const ranked = [...alerts].sort((a, b) => b.severity - a.severity);

  return (
    <section className="shrink-0 border-b border-border bg-surface">
      <div className="flex items-center justify-between px-200 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <AlertTriangle className="h-3.5 w-3.5 text-text-danger" />
          Need you now
        </div>
        <Badge variant={ranked.length ? "destructive" : "secondary"} className="tabular">
          {ranked.length}
        </Badge>
      </div>
      {ranked.length === 0 ? (
        <p className="px-200 pb-150 text-body-small text-text-subtlest">
          No live exceptions. Floor is calm.
        </p>
      ) : (
        <ul className="flex gap-100 overflow-x-auto px-200 pb-150">
          {ranked.map((a) => {
            const call = calls.find((c) => c.id === a.callId);
            if (!call) return null;
            const action = a.recommendedAction ?? call.recommendedAction;
            return (
              <li
                key={a.id}
                className={cn(
                  "w-[22rem] shrink-0 rounded-large border border-border border-l-4 p-150",
                  sevCls[a.severity],
                )}
              >
                <button
                  type="button"
                  onClick={() => onFocus(a.callId)}
                  className="w-full text-left"
                >
                  <div className="flex items-center gap-075">
                    <span className="truncate text-body-small font-semibold text-text">
                      {call.customer}
                    </span>
                    <Lozenge tone="neutral">
                      {call.handler.kind === "human" ? call.handler.name : "Bot"}
                    </Lozenge>
                  </div>
                  <p className="mt-025 line-clamp-2 text-body-small text-text-subtle">{a.reason}</p>
                  <span className="tabular text-body-small text-text-subtlest">{a.at}</span>
                </button>
                <div className="mt-100 flex gap-050">
                  <button
                    type="button"
                    onClick={() => onAction(a.callId, action)}
                    className="flex flex-1 items-center justify-center gap-050 rounded-medium bg-background-danger-bold px-100 py-050 text-body-small font-semibold text-white hover:bg-background-danger-bold-hovered"
                  >
                    <ActionIcon action={action} />
                    {actionLabel[action]}
                  </button>
                  <button
                    type="button"
                    onClick={() => onAck(a.id)}
                    className="flex items-center gap-050 rounded-medium border border-border bg-surface px-100 py-050 text-body-small font-medium text-text-subtle hover:bg-surface-sunken"
                    title="Acknowledge"
                  >
                    <Check className="h-3 w-3" />
                    Ack
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
