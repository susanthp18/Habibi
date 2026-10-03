import { useEffect, useRef, useState } from "react";
import { ArrowDownCircle, Bot, User, Headphones, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/api/handoff";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  turns: TranscriptTurn[];
  speakers?: Record<string, string>;
  /** The bot leg is still on the line: its turns are filed when it ends. */
  callLive: boolean;
};

/**
 * The conversation the bot had before it handed the caller over, as filed
 * when its call ended. Nothing here is live: the person who takes the caller
 * speaks on the callback line, which this page does not hear.
 */
export function Transcript({ turns, speakers, callLive }: Props) {
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
    <section className="relative flex min-h-0 flex-1 flex-col bg-surface">
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-surface px-250 py-100">
        <h2 className="text-body-small font-semibold text-text">Conversation before the handoff</h2>
        <div className="flex items-center gap-150 text-body-small text-text-subtlest">
          <LegendPill color="var(--background-brand-bold)" label="Agent" />
          <LegendPill color="var(--text-primary)" label="Customer" />
          <LegendPill color="var(--warning)" label="Bot" />
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        role="log"
        aria-label="Conversation before the handoff"
        className="min-h-0 flex-1 overflow-y-auto px-250 py-200"
      >
        <div className="mx-auto max-w-3xl space-y-150">
          {turns.length === 0 ? (
            <p className="py-300 text-center text-body-small text-text-subtlest">
              {callLive
                ? "The bot call is still in progress. Its conversation is filed here when it ends."
                : "No conversation was recorded for this call."}
            </p>
          ) : (
            turns.map((t) => <TranscriptBubble key={t.id} turn={t} speakers={speakers} />)
          )}
        </div>
      </div>

      {!autoScroll && (
        <button
          type="button"
          onClick={jumpToBottom}
          className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-075 rounded-full bg-background-brand-bold px-150 py-075 text-body-small font-semibold text-text-inverse shadow-overlay hover:bg-background-brand-bold-hovered"
        >
          <ArrowDownCircle className="h-3.5 w-3.5" />
          Jump to the end
        </button>
      )}
    </section>
  );
}

function LegendPill({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-050">
      <span className="h-100 w-100 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function speakerMeta(sp: TranscriptTurn["speaker"], speakers?: Record<string, string>) {
  switch (sp) {
    case "agent":
      return {
        name: speakers?.agent || "You",
        Icon: Headphones,
        align: "right" as const,
        tone: "brand" as const,
      };
    case "customer":
      return {
        name: speakers?.customer || "Customer",
        Icon: User,
        align: "left" as const,
        tone: "neutral" as const,
      };
    case "bot":
      return {
        name: speakers?.bot || "Bot",
        Icon: Bot,
        align: "left" as const,
        tone: "warn" as const,
      };
    case "system":
      return {
        name: speakers?.system || "System",
        Icon: Info,
        align: "center" as const,
        tone: "system" as const,
      };
    default:
      return {
        name: speakers?.[sp] || sp,
        Icon: User,
        align: "left" as const,
        tone: "neutral" as const,
      };
  }
}

function fmtTime(at: number) {
  const m = Math.floor(at / 60)
    .toString()
    .padStart(2, "0");
  const s = (at % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function TranscriptBubble({
  turn,
  speakers,
}: {
  turn: TranscriptTurn;
  speakers?: Record<string, string>;
}) {
  const meta = speakerMeta(turn.speaker, speakers);

  if (meta.align === "center") {
    return (
      <div className="flex justify-center">
        <Lozenge tone="neutral">
          <meta.Icon />
          {turn.text}
          <span className="tabular text-text-subtlest">· {fmtTime(turn.at)}</span>
        </Lozenge>
      </div>
    );
  }

  const isRight = meta.align === "right";
  return (
    <div className={cn("flex gap-100", isRight ? "justify-end" : "justify-start")}>
      {!isRight && (
        <div
          className={cn(
            "mt-025 grid h-7 w-7 shrink-0 place-items-center rounded-full",
            meta.tone === "warn"
              ? "bg-background-warning text-text-warning"
              : "bg-surface-sunken text-text-subtle",
          )}
        >
          <meta.Icon className="h-3.5 w-3.5" />
        </div>
      )}
      <div className={cn("max-w-[75%]", isRight && "text-right")}>
        <div
          className={cn(
            "mb-025 flex items-center gap-075 text-body-small text-text-subtlest",
            isRight && "justify-end",
          )}
        >
          <span className="font-semibold text-text-subtle">{meta.name}</span>
          <span className="tabular">{fmtTime(turn.at)}</span>
        </div>
        <div
          className={cn(
            "inline-block rounded-large px-150 py-100 text-body leading-relaxed",
            meta.tone === "brand" && "rounded-tr-sm bg-background-brand-bold text-text-inverse",
            meta.tone === "warn" && "rounded-tl-sm bg-background-warning text-text",
            meta.tone === "neutral" && "rounded-tl-sm bg-surface text-text",
          )}
        >
          {turn.text}
        </div>
      </div>
      {isRight && (
        <div className="mt-025 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-background-brand-subtlest text-text-brand">
          <meta.Icon className="h-3.5 w-3.5" />
        </div>
      )}
    </div>
  );
}
