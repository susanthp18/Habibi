import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Mic, MicOff, Play, Send, SkipForward } from "lucide-react";
import type { SandboxTurn } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";

type Props = {
  turns: SandboxTurn[];
  onSend: (text: string) => void;
  onPlayNext: () => void;
  onSkipEnd: () => void;
  awaiting: boolean;
  canPlayNext: boolean;
};

export function ConversationPanel({ turns, onSend, onPlayNext, onSkipEnd, awaiting, canPlayNext }: Props) {
  const [draft, setDraft] = useState("");
  const [recording, setRecording] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, awaiting]);

  const send = () => {
    const t = draft.trim();
    if (!t) return;
    onSend(t);
    setDraft("");
  };

  const holdStart = async () => {
    setRecording(true);
    try {
      // best-effort mic permission for visual affordance only
      if (navigator.mediaDevices?.getUserMedia) {
        await navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => {});
      }
    } catch {}
  };
  const holdEnd = () => {
    if (!recording) return;
    setRecording(false);
    onPlayNext();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface-page">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto flex max-w-3xl flex-col gap-2">
          {turns.map((t) => (
            <TurnBubble key={t.id} turn={t} />
          ))}
          {awaiting && (
            <div className="flex items-center gap-2 self-start rounded-full bg-surface-card px-3 py-1.5 text-[11px] text-text-muted shadow-sm">
              <span className="flex gap-0.5">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-primary [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-primary [animation-delay:120ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-primary [animation-delay:240ms]" />
              </span>
              bot is thinking…
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-card px-4 py-3">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <button
            onClick={onPlayNext}
            disabled={!canPlayNext || awaiting}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-1.5 text-[11.5px] hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
            title="Play next scripted customer turn"
          >
            <Play className="h-3.5 w-3.5" /> Next
          </button>
          <button
            onClick={onSkipEnd}
            disabled={!canPlayNext || awaiting}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-1.5 text-[11.5px] hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
          >
            <SkipForward className="h-3.5 w-3.5" /> Skip
          </button>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Type as the customer…"
            className="flex-1 rounded-md border border-[var(--border-token)] bg-surface-card px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
          />
          <button
            onMouseDown={holdStart}
            onMouseUp={holdEnd}
            onMouseLeave={holdEnd}
            onTouchStart={holdStart}
            onTouchEnd={holdEnd}
            className={cn(
              "grid h-9 w-9 place-items-center rounded-full border transition",
              recording
                ? "border-red-400 bg-red-50 text-red-600 animate-pulse"
                : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
            )}
            title="Hold to speak (mock — advances scripted turn)"
          >
            {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </button>
          <button
            onClick={send}
            disabled={!draft.trim() || awaiting}
            className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-3 py-2 text-[12.5px] font-medium text-white hover:bg-brand-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" /> Send
          </button>
        </div>
      </div>
    </div>
  );
}

function TurnBubble({ turn }: { turn: SandboxTurn }) {
  const [open, setOpen] = useState(false);

  if (turn.role === "system") {
    return (
      <div className="my-1 self-center rounded-full bg-surface-sunken px-3 py-1 text-[11px] text-text-muted">
        {turn.text}
      </div>
    );
  }

  const isBot = turn.role === "bot";
  return (
    <div className={cn("flex", isBot ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-3 py-2 text-[13px] leading-relaxed shadow-sm",
          isBot
            ? "rounded-bl-sm bg-surface-card text-text-primary"
            : "rounded-br-sm bg-brand-primary text-white",
        )}
      >
        <div>{turn.text}</div>
        {isBot && (turn.chunkIds?.length || turn.latencyMs) && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="mt-1 inline-flex items-center gap-1 text-[10.5px] text-text-muted hover:text-text-secondary"
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {turn.latencyMs}ms · {turn.tokens}t · {turn.chunkIds?.length ?? 0} chunks
            {turn.guardrailFlags?.length ? ` · ⚑ ${turn.guardrailFlags.join(",")}` : ""}
          </button>
        )}
        {open && isBot && turn.chunkIds && turn.chunkIds.length > 0 && (
          <div className="mt-1.5 space-y-0.5 border-t border-[var(--border-token)] pt-1.5 font-mono text-[10.5px] text-text-muted">
            {turn.chunkIds.map((id) => <div key={id}>· {id}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}
