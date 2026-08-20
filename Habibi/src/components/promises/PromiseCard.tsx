import { Bot, User, PhoneCall, MessageSquare, Mail, Smartphone, MessageCircle, BellRing, BellOff, CheckCircle2, XCircle, HandCoins, MoreHorizontal } from "lucide-react";
import { fmtDate, fmtMoney, type Promise, type PromiseStatus } from "@/data/promises-seed";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface Props {
  promise: Promise;
  onOpen: (p: Promise) => void;
  onMark: (p: Promise, status: PromiseStatus) => void;
  onResend?: (p: Promise) => void;
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

export function PromiseCard({ promise: p, onOpen, onMark, onResend }: Props) {
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
        "group min-w-0 overflow-hidden rounded-medium border bg-surface p-150 shadow-raised transition-shadow",
        p.status === "broken" ? "border-border-danger-subtle" : "border-border",
      )}
    >
      {p.status === "broken" && (
        <div className="mb-100 -mx-150 -mt-150 rounded-t-md bg-background-danger-bold px-150 py-050 text-body-small font-semibold text-white">
          Auto-routed to follow-up
        </div>
      )}

      <button onClick={() => onOpen(p)} className="w-full text-left">
        <div className="flex items-start justify-between gap-100">
          <div className="min-w-0">
            <div className="truncate text-body font-semibold text-text">{p.customerName}</div>
            <div className="text-body-small text-text-subtlest">
              #{p.accountTail} · {p.id}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-body font-semibold text-text tabular-nums">{fmtMoney(p.amount)}</div>
            {p.status === "partial" && p.paidAmount !== undefined && (
              <div className="text-body-small text-text-warning tabular-nums">
                {fmtMoney(p.paidAmount)} paid
              </div>
            )}
          </div>
        </div>

        <div className="mt-100 flex min-w-0 flex-wrap items-center gap-075">
          <span
            className={cn(
              "rounded px-075 py-025 text-body-small font-medium tabular-nums",
              p.status === "kept"
                ? "bg-background-success-subtler text-text-success-bolder"
                : p.status === "broken"
                  ? "bg-background-danger-subtler text-text-danger-bolder"
                  : p.status === "partial"
                    ? "bg-background-warning-subtler text-text-warning-bolder"
                    : p.status === "due_today"
                      ? "bg-background-warning-subtler text-text-warning-bolder"
                      : "bg-background-brand-subtlest text-text-brand",
            )}
          >
            {dayLabel}
          </span>
          <span className="inline-flex items-center gap-050 rounded bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
            {p.source === "bot" ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
            <CIcon className="h-3 w-3" />
            {p.source === "bot" ? "Bot" : p.source === "agent" ? p.owner.split(" ")[0] : "Self"}
          </span>
          <span
            className={cn(
              "ml-auto inline-flex items-center gap-050 text-body-small",
              p.reminderStatus === "off" ? "text-text-subtlest" : "text-text-subtle",
            )}
          >
            {p.reminderStatus === "off" ? <BellOff className="h-3 w-3" /> : <BellRing className="h-3 w-3" />}
            {p.reminderStatus === "off" ? "Off" : p.reminderStatus === "sent" ? "Sent" : "Scheduled"}
          </span>
        </div>
        {(p.confirmChannel || p.paymentIntentStatus || p.payLinkSent) && (
          <div className="mt-075 text-body-small text-text-subtle">
            {p.payLinkSent
              ? `Link sent via ${p.confirmChannel ?? "message"}${p.phoneLast4 ? ` ···${p.phoneLast4}` : ""}`
              : p.confirmStatus === "suppressed"
                ? "Link suppressed — channel opted out"
                : p.paymentIntentStatus
                  ? `Intent ${p.paymentIntentStatus}`
                  : null}
          </div>
        )}
      </button>

      {(p.status === "upcoming" || p.status === "due_today") && (
        <div className="mt-100 flex min-w-0 flex-wrap items-center gap-050 border-t border-border pt-100 opacity-0 transition-opacity group-hover:opacity-100">
          <Button
            size="sm"
            variant="ghost"
            className="h-300 flex-1 px-100 text-body-small text-text-success-bolder hover:bg-background-success-subtler disabled:opacity-40"
            disabled={!(p.paidAmount && p.paidAmount > 0)}
            title={!(p.paidAmount && p.paidAmount > 0) ? "Kept requires a recorded payment" : undefined}
            onClick={(e) => {
              e.stopPropagation();
              onMark(p, "kept");
            }}
          >
            <CheckCircle2 className="mr-050 h-3 w-3" /> Kept
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-300 flex-1 px-100 text-body-small text-text-warning-bolder hover:bg-background-warning-subtler"
            onClick={(e) => {
              e.stopPropagation();
              onMark(p, "partial");
            }}
          >
            <HandCoins className="mr-050 h-3 w-3" /> Partial
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-300 flex-1 px-100 text-body-small text-text-danger-bolder hover:bg-background-danger-subtler"
            onClick={(e) => {
              e.stopPropagation();
              onMark(p, "broken");
            }}
          >
            <XCircle className="mr-050 h-3 w-3" /> Broken
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-300 w-300 p-0"
            onClick={(e) => {
              e.stopPropagation();
              onOpen(p);
            }}
            aria-label="More"
          >
            <MoreHorizontal className="h-3 w-3" />
          </Button>
          {onResend && (
            <Button
              size="sm"
              variant="ghost"
              className="h-300 px-100 text-body-small"
              onClick={(e) => {
                e.stopPropagation();
                onResend(p);
              }}
            >
              Resend
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
