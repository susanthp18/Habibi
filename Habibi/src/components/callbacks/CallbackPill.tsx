import { AlertTriangle, Phone, MessageSquare, FileText, HeartHandshake, Sparkles, HelpCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtTime, STATUS_TONE, type Callback, type CbReason } from "@/data/callbacks-seed";

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
        "group absolute left-0.5 right-0.5 flex flex-col gap-0.5 rounded-md border border-[var(--border-token)] px-1.5 py-1 text-left text-[10.5px] shadow-sm transition-colors hover:border-brand-primary",
        "bg-surface-card",
        cb.status === "missed" && "border-red-300 bg-red-50",
        cb.status === "in_progress" && "border-amber-400 bg-amber-50",
        cb.status === "completed" && "border-emerald-300 bg-emerald-50/60",
      )}
    >
      <div className="flex items-center gap-1">
        <Icon className="h-3 w-3 shrink-0 text-brand-primary" />
        <span className="font-semibold text-brand-navy tabular-nums">{fmtTime(cb.scheduledAt)}</span>
        <span className="text-text-muted">·{cb.windowMins}m</span>
        {cb.dndActive && (
          <span title="Scheduled inside customer's DND window" className="ml-auto">
            <AlertTriangle className="h-3 w-3 text-amber-600" />
          </span>
        )}
      </div>
      {!compact && (
        <>
          <div className="truncate text-[11px] font-medium text-text-primary">{cb.customerName}</div>
          <div className="flex items-center justify-between gap-1">
            <span className={cn("truncate text-[9.5px] font-semibold rounded px-1 py-px", STATUS_TONE[cb.status])}>
              {cb.status.replace("_", " ")}
            </span>
            <span className="truncate text-[9.5px] text-text-muted">{cb.assignee === "Unassigned" ? "—" : cb.assignee.split(" ")[0]}</span>
          </div>
        </>
      )}
    </button>
  );
}
