import { useEffect, useRef, useState } from "react";
import { Bot, Headphones, MessageCircle, MessageSquare, Phone, PhoneForwarded, ShieldAlert, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { SentimentBubble } from "./SentimentBubble";
import { Waveform } from "./Waveform";
import { channelLabel, type ActiveCall } from "@/data/floor-seed";

const fmtDur = (s: number) => {
  const m = Math.floor(s / 60).toString().padStart(2, "0");
  const r = Math.floor(s % 60).toString().padStart(2, "0");
  return `${m}:${r}`;
};

const ChannelIcon = ({ ch }: { ch: ActiveCall["channel"] }) => {
  const I = ch === "whatsapp" ? MessageCircle : ch === "sms" ? MessageSquare : Phone;
  return <I className="h-3 w-3" />;
};

const riskCls: Record<ActiveCall["risk"], string> = {
  high: "bg-danger-bg text-danger",
  medium: "bg-warning-bg text-warning",
  low: "bg-success-bg text-success",
};

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
        "relative flex min-w-0 flex-col gap-2 rounded-lg border border-[var(--border-token)] border-l-4 bg-surface-card p-3 shadow-card transition-shadow",
        borderCls,
        flash && "ring-2 ring-brand-primary",
      )}
    >
      {listening && (
        <div className="absolute -top-2 left-3 flex items-center gap-1 rounded-full bg-brand-primary px-2 py-0.5 text-[10px] font-semibold text-white shadow-pop">
          <Headphones className="h-2.5 w-2.5" />
          Listening
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold",
            isHuman ? "bg-brand-tint text-brand-primary-dark" : "bg-warning-bg text-warning",
          )}
          title={call.handler.name}
        >
          {isHuman ? call.handler.initials : <Bot className="h-3.5 w-3.5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold text-brand-navy">
              {call.customer}
            </span>
            <span className={cn("rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide", riskCls[call.risk])}>
              {call.risk}
            </span>
          </div>
          <div className="flex items-center gap-1 text-[10px] text-text-muted">
            <User className="h-2.5 w-2.5" />
            <span className="tabular">••{call.accountTail}</span>
            <span>·</span>
            <ChannelIcon ch={call.channel} />
            <span>{channelLabel[call.channel]}</span>
            <span>·</span>
            <span>{call.language}</span>
          </div>
        </div>
        <div className="tabular shrink-0 rounded-md bg-surface-sunken px-1.5 py-0.5 text-[11px] font-semibold text-brand-navy">
          {fmtDur(call.durationSec)}
        </div>
      </div>

      {/* Topic + sentiment */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[10px] font-medium text-text-secondary">
          {call.topic}
        </span>
        <SentimentBubble value={call.sentiment} trend={call.sentimentTrend} />
        {!isHuman && <span className="rounded-full bg-brand-tint px-1.5 py-0.5 text-[9px] font-semibold uppercase text-brand-primary-dark">Bot</span>}
      </div>

      {/* Last line */}
      <div className="flex items-start gap-1.5 rounded-md bg-surface-sunken px-2 py-1.5">
        <span className="mt-0.5 text-[9px] font-semibold uppercase text-text-muted">Live</span>
        <p className="line-clamp-2 flex-1 text-[11px] italic leading-snug text-text-secondary">
          "{call.lastLine}"
        </p>
      </div>

      {/* Waveform for voice */}
      {call.channel === "voice" && <Waveform active className="mt-0.5" />}

      {/* Whisper input inline */}
      {whisperOpen && isHuman && (
        <div className="flex items-center gap-1 rounded-md border border-brand-primary bg-brand-tint/50 p-1">
          <input
            autoFocus
            value={whisperText}
            onChange={(e) => setWhisperText(e.target.value)}
            placeholder="Whisper to agent (they only hear you)…"
            className="h-7 flex-1 rounded bg-surface-card px-2 text-[11px] focus:outline-none"
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
            className="rounded bg-brand-primary px-2 py-1 text-[10px] font-semibold text-white hover:bg-brand-primary-hover"
          >
            Send
          </button>
          <button
            type="button"
            onClick={onWhisperClose}
            className="rounded px-1.5 py-1 text-[10px] text-text-secondary hover:bg-surface-sunken"
          >
            ✕
          </button>
        </div>
      )}

      {/* Barge confirm */}
      {confirmBarge && (
        <div className="rounded-md border border-danger bg-danger-bg p-2 text-[11px] text-danger">
          <div className="flex items-center gap-1 font-semibold">
            <ShieldAlert className="h-3 w-3" />
            Force-handoff to you?
          </div>
          <p className="mt-0.5 text-[10px] text-text-secondary">
            {isHuman ? call.handler.name : "Bot"} will be dropped from this call.
          </p>
          <div className="mt-1 flex justify-end gap-1">
            <button
              type="button"
              onClick={() => setConfirmBarge(false)}
              className="rounded px-2 py-1 text-[10px] font-medium text-text-secondary hover:bg-surface-sunken"
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
              className="rounded bg-danger px-2 py-1 text-[10px] font-semibold text-white hover:bg-[#b3271d]"
            >
              Take over
            </button>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="mt-auto flex items-center justify-between border-t border-[var(--border-token)] pt-2">
        <button
          type="button"
          onClick={onListenToggle}
          className={cn(
            "flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
            listening
              ? "bg-brand-primary text-white hover:bg-brand-primary-hover"
              : "text-text-secondary hover:bg-surface-sunken",
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
            "flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
            !isHuman
              ? "cursor-not-allowed text-text-muted opacity-50"
              : "text-text-secondary hover:bg-surface-sunken",
          )}
          title={isHuman ? "Whisper — agent only" : "Whisper unavailable for bot"}
        >
          <MessageSquare className="h-3 w-3" />
          Whisper
        </button>
        <button
          type="button"
          onClick={() => setConfirmBarge(true)}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-danger hover:bg-danger-bg"
          title="Barge — force handoff"
        >
          <PhoneForwarded className="h-3 w-3" />
          Barge
        </button>
      </div>

      {toast && (
        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 animate-fade-up rounded-full bg-brand-navy px-2.5 py-1 text-[10px] font-semibold text-white shadow-pop">
          {toast}
        </div>
      )}
    </div>
  );
}
