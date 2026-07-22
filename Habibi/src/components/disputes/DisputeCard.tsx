import { Bot, User, Mic, MessageSquare, MoreHorizontal, UserPlus } from "lucide-react";
import {
  SOURCE_LABELS,
  TYPE_LABELS,
  fmtMoney,
  slaInfo,
  type Dispute,
} from "@/data/disputes-seed";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SlaChip } from "./SlaChip";

interface Props {
  dispute: Dispute;
  onOpen: (d: Dispute) => void;
  onAssignMe: (d: Dispute) => void;
}

function sourceIcon(src: Dispute["source"]) {
  if (src === "bot_voice") return Mic;
  if (src === "bot_chat") return MessageSquare;
  return User;
}

const typeTone: Record<Dispute["type"], string> = {
  paid_already: "bg-emerald-50 text-emerald-700",
  wrong_amount: "bg-amber-50 text-amber-700",
  not_my_account: "bg-slate-100 text-slate-700",
  fee_waiver: "bg-brand-tint text-brand-primary-dark",
  duplicate_charge: "bg-orange-50 text-orange-700",
  fraud: "bg-red-50 text-red-700",
};

const priorityDot: Record<Dispute["priority"], string> = {
  low: "bg-slate-300",
  normal: "bg-brand-primary",
  high: "bg-amber-500",
  urgent: "bg-red-500",
};

export function DisputeCard({ dispute: d, onOpen, onAssignMe }: Props) {
  const SIcon = sourceIcon(d.source);
  const sla = slaInfo(d);
  const initials = d.assignee === "Unassigned" ? "?" : d.assignee.split(" ").map((n) => n[0]).slice(0, 2).join("");

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", d.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      className={cn(
        "group rounded-md border bg-surface-card p-2.5 shadow-[var(--shadow-soft)] transition-shadow hover:shadow-md",
        sla.tone === "breach" ? "border-red-200" : "border-[var(--border-token)]",
      )}
    >
      {sla.tone === "breach" && d.status !== "resolved" && d.status !== "rejected" && (
        <div className="mb-2 -mx-2.5 -mt-2.5 rounded-t-md bg-red-500 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-white">
          SLA breached
        </div>
      )}

      <button onClick={() => onOpen(d)} className="w-full text-left">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className={cn("h-1.5 w-1.5 rounded-full", priorityDot[d.priority])} aria-hidden />
              <div className="truncate text-[13px] font-semibold text-brand-navy">{d.customerName}</div>
            </div>
            <div className="text-[11px] text-text-muted">
              #{d.accountTail} · {d.id}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-[14px] font-semibold text-brand-navy tabular-nums">{fmtMoney(d.disputedAmount)}</div>
          </div>
        </div>

        <div className="mt-2 flex items-center gap-1.5">
          <span className={cn("rounded px-1.5 py-0.5 text-[10.5px] font-medium", typeTone[d.type])}>
            {TYPE_LABELS[d.type]}
          </span>
          <span className="inline-flex items-center gap-1 rounded bg-surface-sunken px-1.5 py-0.5 text-[10.5px] text-text-secondary">
            {d.source.startsWith("bot") ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
            <SIcon className="h-3 w-3" />
            {SOURCE_LABELS[d.source]}
          </span>
        </div>

        <p className="mt-2 line-clamp-2 rounded bg-surface-sunken/60 px-2 py-1.5 text-[11.5px] italic text-text-secondary">
          “{d.transcriptSnippet}”
        </p>

        <div className="mt-2 flex items-center justify-between">
          <SlaChip tone={sla.tone} label={sla.label} />
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10.5px]",
              d.assignee === "Unassigned"
                ? "border-dashed border-[var(--border-token)] text-text-muted"
                : "border-[var(--border-token)] text-text-secondary",
            )}
            title={d.assignee}
          >
            <span className="grid h-4 w-4 place-items-center rounded-full bg-brand-tint text-[9px] font-semibold text-brand-primary-dark">
              {initials}
            </span>
            {d.assignee === "Unassigned" ? "Unassigned" : d.assignee.split(" ")[0]}
          </span>
        </div>
      </button>

      <div className="mt-2 flex items-center gap-1 border-t border-[var(--border-token)] pt-2 opacity-0 transition-opacity group-hover:opacity-100">
        {d.assignee === "Unassigned" && (
          <Button
            size="sm"
            variant="ghost"
            className="h-6 flex-1 px-2 text-[11px] text-brand-primary hover:bg-brand-tint"
            onClick={(e) => {
              e.stopPropagation();
              onAssignMe(d);
            }}
          >
            <UserPlus className="mr-1 h-3 w-3" /> Assign me
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-6 w-6 p-0"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(d);
          }}
          aria-label="Open"
        >
          <MoreHorizontal className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}
