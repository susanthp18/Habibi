import { Bot, User, PhoneCall, MessageSquare, Mail, Smartphone, MessageCircle, BellRing, BellOff, CheckCircle2, XCircle, HandCoins, MoreHorizontal } from "lucide-react";
import { fmtDate, fmtMoney, type Promise, type PromiseStatus } from "@/data/promises-seed";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface Props {
  promise: Promise;
  onOpen: (p: Promise) => void;
  onMark: (p: Promise, status: PromiseStatus) => void;
}

const channelIcon = {
  voice: PhoneCall,
  whatsapp: MessageCircle,
  sms: Smartphone,
  chat: MessageSquare,
  email: Mail,
} as const;

function daysDelta(iso: string) {
  const today = new Date().setHours(0, 0, 0, 0);
  const then = new Date(iso).setHours(0, 0, 0, 0);
  return Math.round((then - today) / 86400000);
}

export function PromiseCard({ promise: p, onOpen, onMark }: Props) {
  const CIcon = channelIcon[p.channel];
  const dd = daysDelta(p.promisedDate);
  const dayLabel =
    p.status === "kept" || p.status === "partial" || p.status === "broken"
      ? fmtDate(p.promisedDate, { month: "short", day: "numeric" })
      : dd === 0
        ? "Today"
        : dd > 0
          ? `in ${dd}d`
          : `${Math.abs(dd)}d late`;

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", p.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      className={cn(
        "group rounded-md border bg-surface-card p-2.5 shadow-[var(--shadow-soft)] transition-shadow hover:shadow-md",
        p.status === "broken" ? "border-red-200" : "border-[var(--border-token)]",
      )}
    >
      {p.status === "broken" && (
        <div className="mb-2 -mx-2.5 -mt-2.5 rounded-t-md bg-red-500 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-white">
          Auto-routed to follow-up
        </div>
      )}

      <button onClick={() => onOpen(p)} className="w-full text-left">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold text-brand-navy">{p.customerName}</div>
            <div className="text-[11px] text-text-muted">
              #{p.accountTail} · {p.id}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-[14px] font-semibold text-brand-navy tabular-nums">{fmtMoney(p.amount)}</div>
            {p.status === "partial" && p.paidAmount !== undefined && (
              <div className="text-[10.5px] text-orange-600 tabular-nums">
                {fmtMoney(p.paidAmount)} paid
              </div>
            )}
          </div>
        </div>

        <div className="mt-2 flex items-center gap-1.5">
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10.5px] font-medium tabular-nums",
              p.status === "kept"
                ? "bg-emerald-50 text-emerald-700"
                : p.status === "broken"
                  ? "bg-red-50 text-red-700"
                  : p.status === "partial"
                    ? "bg-orange-50 text-orange-700"
                    : p.status === "due_today"
                      ? "bg-amber-50 text-amber-700"
                      : "bg-brand-tint text-brand-primary-dark",
            )}
          >
            {dayLabel}
          </span>
          <span className="inline-flex items-center gap-1 rounded bg-surface-sunken px-1.5 py-0.5 text-[10.5px] text-text-secondary">
            {p.source === "bot" ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
            <CIcon className="h-3 w-3" />
            {p.source === "bot" ? "Bot" : p.source === "agent" ? p.owner.split(" ")[0] : "Self"}
          </span>
          <span
            className={cn(
              "ml-auto inline-flex items-center gap-1 text-[10.5px]",
              p.reminderStatus === "off" ? "text-text-muted" : "text-text-secondary",
            )}
          >
            {p.reminderStatus === "off" ? <BellOff className="h-3 w-3" /> : <BellRing className="h-3 w-3" />}
            {p.reminderStatus === "off" ? "Off" : p.reminderStatus === "sent" ? "Sent" : "Scheduled"}
          </span>
        </div>
      </button>

      {(p.status === "upcoming" || p.status === "due_today") && (
        <div className="mt-2 flex items-center gap-1 border-t border-[var(--border-token)] pt-2 opacity-0 transition-opacity group-hover:opacity-100">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 flex-1 px-2 text-[11px] text-emerald-700 hover:bg-emerald-50"
            onClick={(e) => {
              e.stopPropagation();
              onMark(p, "kept");
            }}
          >
            <CheckCircle2 className="mr-1 h-3 w-3" /> Kept
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 flex-1 px-2 text-[11px] text-orange-700 hover:bg-orange-50"
            onClick={(e) => {
              e.stopPropagation();
              onMark(p, "partial");
            }}
          >
            <HandCoins className="mr-1 h-3 w-3" /> Partial
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 flex-1 px-2 text-[11px] text-red-700 hover:bg-red-50"
            onClick={(e) => {
              e.stopPropagation();
              onMark(p, "broken");
            }}
          >
            <XCircle className="mr-1 h-3 w-3" /> Broken
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0"
            onClick={(e) => {
              e.stopPropagation();
              onOpen(p);
            }}
            aria-label="More"
          >
            <MoreHorizontal className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  );
}
