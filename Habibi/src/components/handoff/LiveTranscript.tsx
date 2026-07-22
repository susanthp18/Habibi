import { useEffect, useRef, useState } from "react";
import { ArrowDownCircle, Bot, User, Headphones, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Speaker, TranscriptTurn } from "@/data/handoff-seed";

type Props = {
  turns: TranscriptTurn[];
  streaming: boolean;
  latestSpeaker?: Speaker;
};

export function LiveTranscript({ turns, streaming, latestSpeaker }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (!autoScroll) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [turns, autoScroll]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(nearBottom);
  };

  const jumpToBottom = () => {
    setAutoScroll(true);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  return (
    <section className="relative flex min-h-0 flex-1 flex-col bg-surface-app">
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-token)] bg-surface-card px-5 py-2">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-brand-navy">
          Live transcript
          {streaming && (
            <span className="flex items-center gap-1 text-[10px] font-medium text-text-secondary">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
              streaming
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[11px] text-text-muted">
          <LegendPill color="var(--brand-primary)" label="Agent" />
          <LegendPill color="var(--text-primary)" label="Customer" />
          <LegendPill color="var(--warning)" label="Bot" />
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
      >
        <div className="mx-auto max-w-3xl space-y-3">
          {turns.map((t) => (
            <TranscriptBubble key={t.id} turn={t} />
          ))}
          {streaming && latestSpeaker && latestSpeaker !== "system" && (
            <TypingIndicator speaker={latestSpeaker} />
          )}
        </div>
      </div>

      {!autoScroll && (
        <button
          type="button"
          onClick={jumpToBottom}
          className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-brand-primary px-3 py-1.5 text-[11px] font-semibold text-white shadow-pop hover:bg-brand-primary-hover"
        >
          <ArrowDownCircle className="h-3.5 w-3.5" />
          Jump to live
        </button>
      )}
    </section>
  );
}

function LegendPill({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function speakerMeta(sp: Speaker) {
  switch (sp) {
    case "agent":
      return { name: "You", Icon: Headphones, align: "right" as const, tone: "brand" as const };
    case "customer":
      return { name: "Priya Menon", Icon: User, align: "left" as const, tone: "neutral" as const };
    case "bot":
      return { name: "Bot · Kaia", Icon: Bot, align: "left" as const, tone: "warn" as const };
    case "system":
      return { name: "System", Icon: Info, align: "center" as const, tone: "system" as const };
  }
}

function fmtTime(at: number) {
  const m = Math.floor(at / 60).toString().padStart(2, "0");
  const s = (at % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function TranscriptBubble({ turn }: { turn: TranscriptTurn }) {
  const meta = speakerMeta(turn.speaker);

  if (meta.align === "center") {
    return (
      <div className="flex justify-center">
        <div className="inline-flex items-center gap-1.5 rounded-full bg-surface-sunken px-3 py-1 text-[11px] text-text-secondary">
          <meta.Icon className="h-3 w-3" />
          {turn.text}
          <span className="tabular text-text-muted">· {fmtTime(turn.at)}</span>
        </div>
      </div>
    );
  }

  const isRight = meta.align === "right";
  return (
    <div className={cn("flex animate-fade-up gap-2", isRight ? "justify-end" : "justify-start")}>
      {!isRight && (
        <div
          className={cn(
            "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full",
            meta.tone === "warn" ? "bg-warning-bg text-warning" : "bg-surface-sunken text-text-secondary",
          )}
        >
          <meta.Icon className="h-3.5 w-3.5" />
        </div>
      )}
      <div className={cn("max-w-[75%]", isRight && "text-right")}>
        <div className={cn("mb-0.5 flex items-center gap-1.5 text-[11px] text-text-muted", isRight && "justify-end")}>
          <span className="font-semibold text-text-secondary">{meta.name}</span>
          <span className="tabular">{fmtTime(turn.at)}</span>
        </div>
        <div
          className={cn(
            "inline-block rounded-lg px-3 py-2 text-[13px] leading-relaxed shadow-card",
            meta.tone === "brand" && "rounded-tr-sm bg-brand-primary text-white",
            meta.tone === "warn" && "rounded-tl-sm bg-warning-bg text-brand-navy",
            meta.tone === "neutral" && "rounded-tl-sm bg-surface-card text-text-primary",
          )}
        >
          {turn.text}
        </div>
      </div>
      {isRight && (
        <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-tint text-brand-primary-dark">
          <meta.Icon className="h-3.5 w-3.5" />
        </div>
      )}
    </div>
  );
}

function TypingIndicator({ speaker }: { speaker: Speaker }) {
  const meta = speakerMeta(speaker);
  const isRight = meta.align === "right";
  return (
    <div className={cn("flex gap-2", isRight ? "justify-end" : "justify-start")}>
      {!isRight && <div className="h-7 w-7 shrink-0 rounded-full bg-surface-sunken" />}
      <div className="rounded-lg bg-surface-card px-3 py-2 shadow-card">
        <div className="flex gap-1">
          <Dot delay="0ms" />
          <Dot delay="150ms" />
          <Dot delay="300ms" />
        </div>
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted"
      style={{ animationDelay: delay, animationDuration: "900ms" }}
    />
  );
}
