import { Bot, User, Mic, MessageSquare, ShieldCheck, ShieldAlert, CalendarClock, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtMoney, fmtRelative, SOURCE_LABELS, type Lead, type Sentiment } from "@/data/upsell-seed";
import { cn } from "@/lib/utils";

interface Props {
  lead: Lead;
  onOpen: (l: Lead) => void;
}

const sentimentDot: Record<Sentiment, string> = {
  positive: "bg-emerald-500",
  neutral: "bg-slate-400",
  negative: "bg-red-500",
};

const priorityDot: Record<Lead["priority"], string> = {
  low: "bg-slate-300",
  normal: "bg-brand-primary",
  high: "bg-amber-500",
};

export function LeadCard({ lead: l, onOpen }: Props) {
  const failing = l.eligibilityFlags.filter((f) => !f.ok).length;
  const SIcon = l.source === "bot_voice" ? Mic : l.source === "bot_chat" ? MessageSquare : User;
  const initials = l.owner === "Unassigned" ? "?" : l.owner.split(" ").map((n) => n[0]).slice(0, 2).join("");

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", l.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      className="group rounded-md border border-[var(--border-token)] bg-surface-card p-2.5 shadow-[var(--shadow-soft)] transition-shadow hover:shadow-md"
    >
      <button onClick={() => onOpen(l)} className="w-full text-left">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className={cn("h-1.5 w-1.5 rounded-full", priorityDot[l.priority])} aria-hidden />
              <div className="truncate text-[13px] font-semibold text-brand-navy">{l.customerName}</div>
            </div>
            <div className="text-[11px] text-text-muted">#{l.accountTail} · {l.id}</div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-[14px] font-semibold text-brand-navy tabular-nums">
              {fmtMoney(l.stage === "won" ? l.wonAmount ?? l.estimatedValue : l.estimatedValue)}
            </div>
            <div className="text-[10.5px] text-text-muted">{l.offer.indicativeROI}</div>
          </div>
        </div>

        <div className="mt-2 flex items-center gap-1.5">
          <span className="rounded bg-brand-tint px-1.5 py-0.5 text-[10.5px] font-medium text-brand-primary-dark">
            {l.offer.label}
          </span>
          <span className="inline-flex items-center gap-1 rounded bg-surface-sunken px-1.5 py-0.5 text-[10.5px] text-text-secondary">
            {l.source.startsWith("bot") ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
            <SIcon className="h-3 w-3" />
            {SOURCE_LABELS[l.source]}
          </span>
        </div>

        <p className="mt-2 line-clamp-2 rounded bg-surface-sunken/60 px-2 py-1.5 text-[11.5px] italic text-text-secondary">
          “{l.transcriptSnippet}”
        </p>

        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className={cn("h-1.5 w-1.5 rounded-full", sentimentDot[l.sentimentAtCapture])} aria-hidden />
            <span className="text-[10.5px] text-text-muted capitalize">{l.sentimentAtCapture} @ capture</span>
          </div>
          {failing > 0 ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-400 bg-amber-50 px-1.5 py-0.5 text-[10.5px] text-amber-700">
              <ShieldAlert className="h-3 w-3" /> {failing} flag{failing > 1 ? "s" : ""}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-[10.5px] text-emerald-700">
              <ShieldCheck className="h-3 w-3" /> Eligible
            </span>
          )}
        </div>

        <div className="mt-2 flex items-center justify-between">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10.5px]",
              l.owner === "Unassigned"
                ? "border-dashed border-[var(--border-token)] text-text-muted"
                : "border-[var(--border-token)] text-text-secondary",
            )}
            title={l.owner}
          >
            <span className="grid h-4 w-4 place-items-center rounded-full bg-brand-tint text-[9px] font-semibold text-brand-primary-dark">
              {initials}
            </span>
            {l.owner === "Unassigned" ? "Unassigned" : l.owner.split(" ")[0]}
          </span>
          {l.nextFollowUpAt ? (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-text-secondary">
              <CalendarClock className="h-3 w-3" /> {fmtRelative(l.nextFollowUpAt)}
            </span>
          ) : (
            <span className="text-[10.5px] text-text-muted">Captured {fmtRelative(l.capturedAt)}</span>
          )}
        </div>
      </button>

      <div className="mt-2 flex items-center gap-1 border-t border-[var(--border-token)] pt-2 opacity-0 transition-opacity group-hover:opacity-100">
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-6 w-6 p-0"
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
