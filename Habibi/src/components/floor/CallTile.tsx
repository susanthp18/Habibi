import { useEffect, useRef, useState } from "react";
import {
  Bot,
  Headphones,
  MessageCircle,
  MessageSquare,
  Phone,
  PhoneForwarded,
  ShieldAlert,
  User,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SentimentBubble } from "./SentimentBubble";
import { Waveform } from "./Waveform";
import {
  channelLabel,
  LIVE_QA_STATUS_LABEL,
  LIVE_QA_STATUS_TONE,
  type ActiveCall,
} from "@/data/floor-seed";
import { OFFER_STATUS_LABEL, OFFER_STATUS_TONE } from "@/lib/offer-policy";
import { AUTHORITY_STATUS_LABEL, AUTHORITY_STATUS_TONE } from "@/lib/authority-policy";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";

const fmtDur = (s: number) => {
  const m = Math.floor(s / 60)
    .toString()
    .padStart(2, "0");
  const r = Math.floor(s % 60)
    .toString()
    .padStart(2, "0");
  return `${m}:${r}`;
};

const ChannelIcon = ({ ch }: { ch: ActiveCall["channel"] }) => {
  const I = ch === "whatsapp" ? MessageCircle : ch === "sms" ? MessageSquare : Phone;
  return <I className="h-3 w-3" />;
};

const riskTone = {
  high: "danger",
  medium: "warning",
  low: "success",
} as const satisfies Record<ActiveCall["risk"], LozengeProps["tone"]>;

type Props = {
  call: ActiveCall;
  listening: boolean;
  whisperOpen: boolean;
  onListenToggle: () => void;
  onWhisperOpen: () => void;
  onWhisperSubmit: (text: string) => void;
  onWhisperClose: () => void;
  onBarge: () => void;
  flash?: boolean;
};

export function CallTile({
  call,
  listening,
  whisperOpen,
  onListenToggle,
  onWhisperOpen,
  onWhisperSubmit,
  onWhisperClose,
  onBarge,
  flash,
}: Props) {
  const [whisperText, setWhisperText] = useState("");
  const [confirmBarge, setConfirmBarge] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (flash && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [flash]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 1800);
    return () => window.clearTimeout(t);
  }, [toast]);

  const borderCls =
    call.sentiment > 0.25
      ? "border-l-[var(--sentiment-positive)]"
      : call.sentiment < -0.2
        ? "border-l-[var(--sentiment-negative)]"
        : "border-l-[var(--sentiment-neutral)]";

  const isHuman = call.handler.kind === "human";

  return (
    <div
      ref={ref}
      className={cn(
        "relative flex min-w-0 flex-col gap-100 rounded-large border border-border border-l-4 bg-surface p-150 transition-shadow",
        borderCls,
        flash && "ring-2 ring-border-brand",
      )}
    >
      {listening && (
        <div className="absolute -top-2 left-3 flex items-center gap-050 rounded-full bg-background-brand-bold px-100 py-025 text-body-small font-semibold text-white shadow-overlay">
          <Headphones className="h-2.5 w-2.5" />
          Listening
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-100">
        <div
          className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-full text-body-small font-semibold",
            isHuman
              ? "bg-background-brand-subtlest text-text-brand"
              : "bg-background-warning text-text-warning",
          )}
          title={call.handler.name}
        >
          {isHuman ? call.handler.initials : <Bot className="h-3.5 w-3.5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-075">
            <span className="truncate text-body font-semibold text-text">{call.customer}</span>
            <Lozenge tone={riskTone[call.risk]}>{call.risk}</Lozenge>
          </div>
          <div className="flex items-center gap-050 text-body-small text-text-subtlest">
            <User className="h-2.5 w-2.5" />
            <span className="tabular">••{call.accountTail}</span>
            <span>·</span>
            <ChannelIcon ch={call.channel} />
            <span>{channelLabel[call.channel]}</span>
            <span>·</span>
            <span>{call.language}</span>
          </div>
        </div>
        <div className="tabular shrink-0 rounded-medium bg-surface-sunken px-075 py-025 text-body-small font-semibold text-text">
          {fmtDur(call.durationSec)}
        </div>
      </div>

      {/* Topic + sentiment */}
      <div className="flex flex-wrap items-center gap-075">
        <Lozenge tone="neutral">{call.topic}</Lozenge>
        {call.offerPolicy && call.offerPolicy.status !== "none" ? (
          <Lozenge tone={OFFER_STATUS_TONE[call.offerPolicy.status]}>
            {OFFER_STATUS_LABEL[call.offerPolicy.status]}
          </Lozenge>
        ) : null}
        {call.authorityPolicy && call.authorityPolicy.status !== "none" ? (
          <Lozenge tone={AUTHORITY_STATUS_TONE[call.authorityPolicy.status]}>
            {AUTHORITY_STATUS_LABEL[call.authorityPolicy.status]}
          </Lozenge>
        ) : null}
        {call.liveQa && call.liveQa.status && call.liveQa.status !== "none" ? (
          <Lozenge tone={LIVE_QA_STATUS_TONE[call.liveQa.status] ?? "warning"}>
            {LIVE_QA_STATUS_LABEL[call.liveQa.status] ??
              call.liveQa.reason?.replace(/-/g, " ") ??
              "Live QA"}
          </Lozenge>
        ) : null}
        <SentimentBubble value={call.sentiment} trend={call.sentimentTrend} />
        {!isHuman && <Lozenge tone="selected">{call.agentCard?.displayName ?? "Bot"}</Lozenge>}
      </div>

      {/* Last line */}
      <div className="flex items-start gap-075 rounded-medium bg-surface-sunken px-100 py-075">
        <span className="mt-025 text-body-small font-semibold text-text-subtlest">Live</span>
        <p className="line-clamp-2 flex-1 text-body-small italic leading-snug text-text-subtle">
          "{call.lastLine}"
        </p>
      </div>

      {/* Waveform for voice */}
      {call.channel === "voice" && <Waveform active className="mt-025" />}

      {/* Whisper input inline */}
      {whisperOpen && isHuman && (
        <div className="flex items-center gap-050 rounded-medium border border-border-brand bg-background-brand-subtlest/50 p-050">
          <input
            autoFocus
            value={whisperText}
            onChange={(e) => setWhisperText(e.target.value)}
            placeholder="Whisper to agent (they only hear you)…"
            className="h-7 flex-1 rounded bg-surface px-100 text-body-small focus:outline-none"
          />
          <button
            type="button"
            onClick={() => {
              if (whisperText.trim()) {
                onWhisperSubmit(whisperText.trim());
                setWhisperText("");
                setToast("Whisper sent to agent");
              }
            }}
            className="rounded bg-background-brand-bold px-100 py-050 text-body-small font-semibold text-white hover:bg-background-brand-bold-hovered"
          >
            Send
          </button>
          <button
            type="button"
            onClick={onWhisperClose}
            aria-label="Close whisper"
            className="rounded px-075 py-050 text-body-small text-text-subtle hover:bg-surface-sunken"
          >
            <X className="size-3" aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Barge confirm */}
      {confirmBarge && (
        <div className="rounded-medium border border-border-danger bg-background-danger p-100 text-body-small text-text-danger">
          <div className="flex items-center gap-050 font-semibold">
            <ShieldAlert className="h-3 w-3" />
            Force-handoff to you?
          </div>
          <p className="mt-025 text-body-small text-text-subtle">
            {isHuman ? call.handler.name : "Bot"} will be dropped from this call.
          </p>
          <div className="mt-050 flex justify-end gap-050">
            <button
              type="button"
              onClick={() => setConfirmBarge(false)}
              className="rounded px-100 py-050 text-body-small font-medium text-text-subtle hover:bg-surface-sunken"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmBarge(false);
                onBarge();
                setToast("Handoff taken · you are now on the call");
              }}
              className="rounded bg-background-danger-bold px-100 py-050 text-body-small font-semibold text-white hover:bg-background-danger-bold-hovered"
            >
              Take over
            </button>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="mt-auto flex items-center justify-between border-t border-border pt-100">
        <button
          type="button"
          onClick={onListenToggle}
          className={cn(
            "flex items-center gap-050 rounded-medium px-100 py-050 text-body-small font-medium transition-colors",
            listening
              ? "bg-background-brand-bold text-white hover:bg-background-brand-bold-hovered"
              : "text-text-subtle hover:bg-surface-sunken",
          )}
          title="Silent listen-in"
        >
          <Headphones className="h-3 w-3" />
          {listening ? "Stop" : "Listen"}
        </button>
        <button
          type="button"
          onClick={onWhisperOpen}
          disabled={!isHuman}
          className={cn(
            "flex items-center gap-050 rounded-medium px-100 py-050 text-body-small font-medium transition-colors",
            !isHuman
              ? "cursor-not-allowed text-text-subtlest opacity-50"
              : "text-text-subtle hover:bg-surface-sunken",
          )}
          title={isHuman ? "Whisper — agent only" : "Whisper unavailable for bot"}
        >
          <MessageSquare className="h-3 w-3" />
          Whisper
        </button>
        <button
          type="button"
          onClick={() => setConfirmBarge(true)}
          className="flex items-center gap-050 rounded-medium px-100 py-050 text-body-small font-medium text-text-danger hover:bg-background-danger"
          title="Barge — force handoff"
        >
          <PhoneForwarded className="h-3 w-3" />
          Barge
        </button>
      </div>

      {toast && (
        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 animate-fade-up rounded-full bg-background-brand-boldest px-150 py-050 text-body-small font-semibold text-white shadow-overlay">
          {toast}
        </div>
      )}
    </div>
  );
}
