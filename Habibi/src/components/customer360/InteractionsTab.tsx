import { useMemo, useState } from "react";
import { ArrowDown, ArrowRight, ArrowUp, Bot, ChevronDown, ChevronRight, Mail, MessageCircle, MessageSquare, PhoneCall, Sparkles, User2 } from "lucide-react";
import { toast } from "sonner";
import type { Channel, Customer, Interaction, Sentiment } from "@/data/customer360-seed";
import { fmtDateTime, fmtRelative } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

const CHANNEL_ICON: Record<Channel, React.ComponentType<{ className?: string }>> = {
  voice: PhoneCall,
  whatsapp: MessageCircle,
  chat: MessageSquare,
  email: Mail,
  sms: MessageSquare,
};

const CHANNEL_LABEL: Record<Channel, string> = {
  voice: "Voice",
  whatsapp: "WhatsApp",
  chat: "Web Chat",
  email: "Email",
  sms: "SMS",
};

const SENT_TONE: Record<Sentiment, string> = {
  positive: "text-success bg-success-bg",
  neutral: "text-warning bg-warning-bg",
  negative: "text-danger bg-danger-bg",
};

const CHANNELS: Channel[] = ["voice", "whatsapp", "chat", "email"];

export function InteractionsTab({ customer }: { customer: Customer }) {
  const [openId, setOpenId] = useState<string | null>(customer.interactions[0]?.id ?? null);
  const [channel, setChannel] = useState<"all" | Channel>("all");
  const [handler, setHandler] = useState<"all" | "bot" | "human">("all");
  const [sentiment, setSentiment] = useState<"all" | Sentiment>("all");

  const rows = useMemo(() => {
    return customer.interactions.filter((i) => {
      if (channel !== "all" && i.channel !== channel) return false;
      if (handler !== "all" && i.handler.kind !== handler) return false;
      if (sentiment !== "all" && i.sentiment !== sentiment) return false;
      return true;
    });
  }, [customer.interactions, channel, handler, sentiment]);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface-card p-2 text-xs">
        <FilterGroup label="Channel">
          <Chip active={channel === "all"} onClick={() => setChannel("all")}>All</Chip>
          {CHANNELS.map((c) => (
            <Chip key={c} active={channel === c} onClick={() => setChannel(c)}>
              {CHANNEL_LABEL[c]}
            </Chip>
          ))}
        </FilterGroup>
        <FilterGroup label="Handler">
          <Chip active={handler === "all"} onClick={() => setHandler("all")}>All</Chip>
          <Chip active={handler === "bot"} onClick={() => setHandler("bot")}>Bot</Chip>
          <Chip active={handler === "human"} onClick={() => setHandler("human")}>Human</Chip>
        </FilterGroup>
        <FilterGroup label="Sentiment">
          <Chip active={sentiment === "all"} onClick={() => setSentiment("all")}>All</Chip>
          <Chip active={sentiment === "positive"} onClick={() => setSentiment("positive")} tone="success">Positive</Chip>
          <Chip active={sentiment === "neutral"} onClick={() => setSentiment("neutral")} tone="warning">Neutral</Chip>
          <Chip active={sentiment === "negative"} onClick={() => setSentiment("negative")} tone="danger">Negative</Chip>
        </FilterGroup>
      </div>

      {/* Timeline */}
      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-surface-card p-10 text-center text-sm text-text-muted">
          No interactions match these filters.
        </div>
      ) : (
        <ol className="relative space-y-3 border-l-2 border-border pl-6">
          {rows.map((i) => (
            <InteractionCard key={i.id} i={i} open={openId === i.id} onToggle={() => setOpenId((cur) => (cur === i.id ? null : i.id))} />
          ))}
        </ol>
      )}
    </div>
  );
}

function InteractionCard({ i, open, onToggle }: { i: Interaction; open: boolean; onToggle: () => void }) {
  const Icon = CHANNEL_ICON[i.channel];
  const Chev = open ? ChevronDown : ChevronRight;
  const HandlerIcon = i.handler.kind === "bot" ? Bot : User2;
  const Delta = i.sentimentDelta === "up" ? ArrowUp : i.sentimentDelta === "down" ? ArrowDown : ArrowRight;

  return (
    <li className="relative">
      <span className="absolute -left-[31px] top-2 flex h-5 w-5 items-center justify-center rounded-full border border-border bg-surface-card text-brand-primary">
        <Icon className="h-3 w-3" />
      </span>
      <div className="rounded-lg border border-border bg-surface-card">
        <button onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-brand-tint/30">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-text-primary">{CHANNEL_LABEL[i.channel]}</span>
              <span className="inline-flex items-center gap-1 text-xs text-text-secondary">
                <HandlerIcon className="h-3 w-3" />
                {i.handler.name}
              </span>
              <span className="text-xs text-text-muted">· {i.duration}</span>
              <span className="text-xs text-text-muted">· {i.disposition}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{i.summary}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-xs">
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium capitalize", SENT_TONE[i.sentiment])}>
              <Delta className="h-3 w-3" />
              {i.sentiment}
            </span>
            <span className="text-text-muted tabular">{fmtRelative(i.startedAt)}</span>
            <Chev className="h-4 w-4 text-text-muted" />
          </div>
        </button>
        {open && (
          <div className="border-t border-border bg-surface-sunken/60 px-4 py-3">
            <div className="mb-2 grid grid-cols-3 gap-2 text-[11px]">
              <IntentPill label="Query resolved" active={!!i.intents.queryResolved} />
              <IntentPill label="Upsell presented" active={!!i.intents.upsellPresented} />
              <IntentPill label="PTP captured" active={!!i.intents.ptpCaptured} />
            </div>
            <div className="text-xs text-text-primary">
              <span className="font-semibold text-brand-navy">Summary. </span>
              {i.summary}
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-text-secondary">
              <span>{fmtDateTime(i.startedAt)}</span>
              <button
                onClick={() => toast.info("Opens transcript in Audit Trail — coming soon.")}
                className="inline-flex items-center gap-1 font-medium text-brand-primary hover:underline"
              >
                <Sparkles className="h-3 w-3" /> Open transcript
              </button>
            </div>
          </div>
        )}
      </div>
    </li>
  );
}

function IntentPill({ label, active }: { label: string; active: boolean }) {
  return (
    <span
      className={cn(
        "rounded-md border px-2 py-1 text-center font-medium",
        active
          ? "border-success/30 bg-success-bg text-success"
          : "border-border bg-surface-card text-text-muted",
      )}
    >
      {active ? "✓ " : "— "}
      {label}
    </span>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{label}</span>
      <div className="flex gap-1">{children}</div>
    </div>
  );
}

function Chip({
  children,
  active,
  onClick,
  tone = "brand",
}: {
  children: React.ReactNode;
  active?: boolean;
  onClick: () => void;
  tone?: "brand" | "success" | "warning" | "danger";
}) {
  const activeClass =
    tone === "success"
      ? "bg-success text-white border-success"
      : tone === "warning"
      ? "bg-warning text-white border-warning"
      : tone === "danger"
      ? "bg-danger text-white border-danger"
      : "bg-brand-primary text-white border-brand-primary";
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px] font-medium",
        active ? activeClass : "border-border bg-surface-card text-text-secondary hover:bg-brand-tint hover:text-brand-primary-dark",
      )}
    >
      {children}
    </button>
  );
}
