import { Bot, User, Mic, MessageSquare, ShieldCheck, ShieldAlert, CalendarClock, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtMoney, fmtRelative, leadValue, SOURCE_LABELS, type Lead, type Sentiment } from "@/data/upsell-seed";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

interface Props {
  lead: Lead;
  onOpen: (l: Lead) => void;
}

const sentimentDot: Record<Sentiment, string> = {
  positive: "bg-background-success-bold",
  neutral: "bg-background-accent-gray-subtle",
  negative: "bg-background-danger-bold",
};

const priorityDot: Record<Lead["priority"], string> = {
  low: "bg-background-accent-gray-subtle",
  normal: "bg-background-brand-bold",
  high: "bg-background-warning-bold",
};

export function LeadCard({ lead: l, onOpen }: Props) {
  const failing = l.eligibilityFlags.filter((f) => !f.ok).length;
  const SIcon = l.source === "bot_voice" ? Mic : l.source === "bot_chat" ? MessageSquare : User;
  const owner = l.owner ?? "Unassigned";
  const initials = owner === "Unassigned" ? "?" : owner.split(" ").map((n) => n[0]).slice(0, 2).join("");

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", l.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      className="group rounded-medium border border-border bg-surface p-150 shadow-raised transition-shadow"
    >
      <button onClick={() => onOpen(l)} className="w-full text-left">
        <div className="flex items-start justify-between gap-100">
          <div className="min-w-0">
            <div className="flex items-center gap-075">
              <span className={cn("h-1.5 w-1.5 rounded-full", priorityDot[l.priority])} aria-hidden />
              <div className="truncate text-body font-semibold text-text">{l.customerName}</div>
            </div>
            <div className="text-body-small text-text-subtlest">#{l.accountTail} · {l.id}</div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-body font-semibold text-text tabular-nums">
              {fmtMoney(leadValue(l))}
            </div>
            <div className="text-body-small text-text-subtlest">{l.offer.indicativeROI}</div>
          </div>
        </div>

        <div className="mt-100 flex items-center gap-075">
          <span className="rounded bg-background-brand-subtlest px-075 py-025 text-body-small font-medium text-text-brand">
            {l.offer.label}
          </span>
          <span className="inline-flex items-center gap-050 rounded bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
            {l.source.startsWith("bot") ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
            <SIcon className="h-3 w-3" />
            {SOURCE_LABELS[l.source]}
          </span>
        </div>

        <p className="mt-100 line-clamp-2 rounded bg-surface-sunken/60 px-100 py-075 text-body-small italic text-text-subtle">
          “{l.transcriptSnippet}”
        </p>

        <div className="mt-100 flex items-center justify-between gap-100">
          <div className="flex items-center gap-075">
            <span className={cn("h-1.5 w-1.5 rounded-full", sentimentDot[l.sentimentAtCapture])} aria-hidden />
            <span className="text-body-small text-text-subtlest capitalize">{l.sentimentAtCapture} @ capture</span>
          </div>
          {failing > 0 ? (
            <Lozenge tone="warning" className="border-border-warning">
              <ShieldAlert className="h-3 w-3" /> {failing} flag{failing > 1 ? "s" : ""}
            </Lozenge>
          ) : (
            <Lozenge tone="success" className="border-border-success">
              <ShieldCheck className="h-3 w-3" /> Eligible
            </Lozenge>
          )}
        </div>

        <div className="mt-100 flex items-center justify-between">
          <Lozenge
            tone="neutral"
            className={cn(owner === "Unassigned" && "border-dashed")}
            title={owner}
          >
            <span className="grid h-4 w-4 place-items-center rounded-full bg-background-brand-subtlest text-body-small font-semibold text-text-brand">
              {initials}
            </span>
            {owner === "Unassigned" ? "Unassigned" : owner.split(" ")[0]}
          </Lozenge>
          {l.nextFollowUpAt ? (
            <span className="inline-flex items-center gap-050 text-body-small text-text-subtle">
              <CalendarClock className="h-3 w-3" /> {fmtRelative(l.nextFollowUpAt)}
            </span>
          ) : (
            <span className="text-body-small text-text-subtlest">Captured {fmtRelative(l.capturedAt)}</span>
          )}
        </div>
      </button>

      <div className="mt-100 flex items-center gap-050 border-t border-border pt-100 opacity-0 transition-opacity group-hover:opacity-100">
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-300 w-300 p-0"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(l);
          }}
          aria-label="Open"
        >
          <MoreHorizontal className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}
