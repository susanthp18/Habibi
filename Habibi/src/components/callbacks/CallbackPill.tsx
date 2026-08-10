import { AlertTriangle, Phone, MessageSquare, FileText, HeartHandshake, Sparkles, HelpCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtTime, type Callback, type CbReason, type CbStatus } from "@/data/callbacks-seed";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";

const STATUS_LOZENGE_TONE: Record<CbStatus, NonNullable<LozengeProps["tone"]>> = {
  scheduled: "information",
  reminded: "discovery",
  in_progress: "warning",
  completed: "success",
  missed: "danger",
  rescheduled: "neutral",
  cancelled: "neutral",
};

const ICON: Record<CbReason, LucideIcon> = {
  payment_discussion: Phone,
  dispute_followup: AlertTriangle,
  document_query: FileText,
  hardship_review: HeartHandshake,
  upsell_interest: Sparkles,
  general: HelpCircle,
};

export function CallbackPill({
  cb,
  onOpen,
  onDragStart,
  style,
  compact,
}: {
  cb: Callback;
  onOpen: () => void;
  onDragStart?: (e: React.DragEvent) => void;
  style?: React.CSSProperties;
  compact?: boolean;
}) {
  const Icon = ICON[cb.reason];
  return (
    <button
      draggable={!!onDragStart}
      onDragStart={onDragStart}
      onClick={onOpen}
      style={style}
      className={cn(
        "group absolute left-0.5 right-0.5 flex flex-col gap-025 rounded-medium border border-border px-075 py-050 text-left text-body-small transition-colors hover:border-border-brand",
        "bg-surface",
        cb.status === "missed" && "border-border-danger bg-background-danger-subtler",
        cb.status === "in_progress" && "border-border-warning bg-background-warning-subtler",
        cb.status === "completed" && "border-border-success bg-background-success-subtler/60",
      )}
    >
      <div className="flex items-center gap-050">
        <Icon className="h-3 w-3 shrink-0 text-text-brand" />
        <span className="font-semibold text-text tabular-nums">{fmtTime(cb.scheduledAt)}</span>
        <span className="text-text-subtlest">·{cb.windowMins}m</span>
        {cb.dndActive && (
          <span title="Scheduled inside customer's DND window" className="ml-auto">
            <AlertTriangle className="h-3 w-3 text-text-warning" />
          </span>
        )}
      </div>
      {!compact && (
        <>
          <div className="truncate text-body-small font-medium text-text">{cb.customerName}</div>
          <div className="flex items-center justify-between gap-050">
            <Lozenge tone={STATUS_LOZENGE_TONE[cb.status]} className="truncate">
              {cb.status.replace("_", " ")}
            </Lozenge>
            <span className="truncate text-body-small text-text-subtlest">{cb.assignee === "Unassigned" ? "—" : cb.assignee.split(" ")[0]}</span>
          </div>
        </>
      )}
    </button>
  );
}
