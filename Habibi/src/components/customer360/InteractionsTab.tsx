import { useMemo, useState } from "react";
import { ArrowDown, ArrowRight, ArrowUp, Bot, Check, ChevronDown, ChevronRight, Mail, MessageCircle, MessageSquare, Minus, PhoneCall, Sparkles, User2 } from "lucide-react";
import { toast } from "sonner";
import type { Channel, Customer, Interaction, Sentiment } from "@/data/customer360-seed";
import { fmtDateTime, fmtRelative } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

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

const SENT_TONE: Record<Sentiment, LozengeTone> = {
  positive: "success",
  neutral: "warning",
  negative: "danger",
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
    <div className="space-y-200">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-100 rounded-medium border border-border bg-surface p-100 text-xs">
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
        <div className="rounded-large border border-dashed border-border bg-surface p-500 text-center text-sm text-text-subtlest">
          No interactions match these filters.
        </div>
      ) : (
        <ol className="relative space-y-150 border-l-2 border-border pl-300">
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
      <span className="absolute -left-400 top-2 flex h-250 w-250 items-center justify-center rounded-full border border-border bg-surface text-text-brand">
        <Icon className="h-3 w-3" />
      </span>
      <div className="rounded-large border border-border bg-surface">
        <button onClick={onToggle} className="flex w-full items-start gap-150 px-200 py-150 text-left hover:bg-background-brand-subtlest/30">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-100 text-sm">
              <span className="font-medium text-text">{CHANNEL_LABEL[i.channel]}</span>
              <span className="inline-flex items-center gap-050 text-xs text-text-subtle">
                <HandlerIcon className="h-3 w-3" />
                {i.handler.name}
              </span>
              <span className="text-xs text-text-subtlest">· {i.duration}</span>
              <span className="text-xs text-text-subtlest">· {i.disposition}</span>
            </div>
            <p className="mt-050 line-clamp-2 text-xs text-text-subtle">{i.summary}</p>
          </div>
          <div className="flex shrink-0 items-center gap-100 text-xs">
            <Lozenge tone={SENT_TONE[i.sentiment]} className="capitalize">
              <Delta />
              {i.sentiment}
            </Lozenge>
            <span className="text-text-subtlest tabular">{fmtRelative(i.startedAt)}</span>
            <Chev className="h-4 w-4 text-text-subtlest" />
          </div>
        </button>
        {open && (
          <div className="border-t border-border bg-surface-sunken/60 px-200 py-150">
            <div className="mb-100 grid grid-cols-3 gap-100 text-body-small">
              <IntentPill label="Query resolved" active={!!i.intents.queryResolved} />
              <IntentPill label="Upsell presented" active={!!i.intents.upsellPresented} />
              <IntentPill label="PTP captured" active={!!i.intents.ptpCaptured} />
            </div>
            <div className="text-xs text-text">
              <span className="font-semibold text-text">Summary. </span>
              {i.summary}
            </div>
            <div className="mt-100 flex items-center justify-between text-body-small text-text-subtle">
              <span>{fmtDateTime(i.startedAt)}</span>
              <button
                onClick={() => toast.info("Opens transcript in Audit Trail — coming soon.")}
                className="inline-flex items-center gap-050 font-medium text-text-brand hover:underline"
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
        "inline-flex items-center gap-050 rounded-medium border px-100 py-050 text-center font-medium",
        active
          ? "border-border-success/30 bg-background-success text-text-success"
          : "border-border bg-surface text-text-subtlest",
      )}
    >
      {active ? <Check aria-hidden="true" className="size-3" /> : <Minus aria-hidden="true" className="size-3" />}
      {label}
    </span>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-050">
      <span className="text-body-small font-semibold text-text-subtlest">{label}</span>
      <div className="flex gap-050">{children}</div>
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
      ? "bg-background-success-bold text-white border-border-success"
      : tone === "warning"
      ? "bg-background-warning-bold text-text-warning-inverse border-border-warning"
      : tone === "danger"
      ? "bg-background-danger-bold text-white border-border-danger"
      : "bg-background-brand-bold text-white border-border-brand";
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-medium border px-100 py-025 text-body-small font-medium",
        active ? activeClass : "border-border bg-surface text-text-subtle hover:bg-background-brand-subtlest hover:text-text-brand",
      )}
    >
      {children}
    </button>
  );
}
