import { Bot, User, Mic, MessageSquare, MoreHorizontal, UserPlus } from "lucide-react";
import {
  SOURCE_LABELS,
  TYPE_LABELS,
  fmtMoney,
  slaInfo,
  type Dispute,
} from "@/data/disputes-seed";
import { Lozenge } from "@/components/ui/lozenge";
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
  paid_already: "bg-background-success-subtler text-text-success-bolder",
  wrong_amount: "bg-background-warning-subtler text-text-warning-bolder",
  not_my_account: "bg-background-accent-gray-subtler text-text-accent-gray-bolder",
  fee_waiver: "bg-background-brand-subtlest text-text-brand",
  duplicate_charge: "bg-background-warning-subtler text-text-warning-bolder",
  fraud: "bg-background-danger-subtler text-text-danger-bolder",
};

const priorityDot: Record<Dispute["priority"], string> = {
  low: "bg-background-accent-gray-subtle",
  normal: "bg-background-brand-bold",
  high: "bg-background-warning-bold",
  urgent: "bg-background-danger-bold",
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
        "group rounded-medium border bg-surface p-150 shadow-raised transition-shadow",
        sla.tone === "breach" ? "border-border-danger-subtle" : "border-border",
      )}
    >
      {sla.tone === "breach" && d.status !== "resolved" && d.status !== "rejected" && (
        <div className="mb-100 -mx-150 -mt-150 rounded-t-md bg-background-danger-bold px-150 py-050 text-body-small font-semibold text-white">
          SLA breached
        </div>
      )}

      <button onClick={() => onOpen(d)} className="w-full text-left">
        <div className="flex items-start justify-between gap-100">
          <div className="min-w-0">
            <div className="flex items-center gap-075">
              <span className={cn("h-1.5 w-1.5 rounded-full", priorityDot[d.priority])} aria-hidden />
              <div className="truncate text-body font-semibold text-text">{d.customerName}</div>
            </div>
            <div className="text-body-small text-text-subtlest">
              #{d.accountTail} · {d.id}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-body font-semibold text-text tabular-nums">{fmtMoney(d.disputedAmount)}</div>
          </div>
        </div>

        <div className="mt-100 flex items-center gap-075">
          <span className={cn("rounded px-075 py-025 text-body-small font-medium", typeTone[d.type])}>
            {TYPE_LABELS[d.type]}
          </span>
          <span className="inline-flex items-center gap-050 rounded bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
            {d.source.startsWith("bot") ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
            <SIcon className="h-3 w-3" />
            {SOURCE_LABELS[d.source]}
          </span>
        </div>

        <p className="mt-100 line-clamp-2 rounded bg-surface-sunken/60 px-100 py-075 text-body-small italic text-text-subtle">
          “{d.transcriptSnippet}”
        </p>

        <div className="mt-100 flex items-center justify-between">
          <SlaChip tone={sla.tone} label={sla.label} />
          <Lozenge
            tone="neutral"
            className={cn(d.assignee === "Unassigned" && "border-dashed")}
            title={d.assignee}
          >
            <span className="grid h-4 w-4 place-items-center rounded-full bg-background-brand-subtlest text-body-small font-semibold text-text-brand">
              {initials}
            </span>
            {d.assignee === "Unassigned" ? "Unassigned" : d.assignee.split(" ")[0]}
          </Lozenge>
        </div>
      </button>

      <div className="mt-100 flex items-center gap-050 border-t border-border pt-100 opacity-0 transition-opacity group-hover:opacity-100">
        {d.assignee === "Unassigned" && (
          <Button
            size="sm"
            variant="ghost"
            className="h-300 flex-1 px-100 text-body-small text-text-brand hover:bg-background-brand-subtlest"
            onClick={(e) => {
              e.stopPropagation();
              onAssignMe(d);
            }}
          >
            <UserPlus className="mr-050 h-3 w-3" /> Assign me
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-300 w-300 p-0"
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
