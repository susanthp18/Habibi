import { useEffect, useRef, useState } from "react";
import {
  Paperclip,
  SendHorizontal,
  Smile,
  Sparkles,
  Zap,
  ChevronUp,
  ChevronDown,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread } from "@/data/inbox-seed";
import { useCannedResponses } from "@/api/inbox";

const EMOJIS = ["👍", "🙏", "✅", "🙂", "😮", "😂", "📎", "₹", "⏰", "✔️", "❗", "👋", "🤝", "💯", "⚠️"];

function SuggestionCard({
  text,
  onUse,
  index,
  expanded,
  onToggle,
}: {
  text: string;
  onUse: (value: string) => void;
  index: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const trimmed = text.trim();
  const long = trimmed.length > 160;
  // Backend format: "Doc title — Heading\n\nfull snippet"
  const splitAt = trimmed.indexOf("\n\n");
  let title: string | null = null;
  let body = trimmed;
  if (splitAt > 0 && splitAt < 160) {
    title = trimmed.slice(0, splitAt).trim();
    body = trimmed.slice(splitAt + 2).trim();
  } else {
    const colon = trimmed.indexOf(": ");
    if (colon > 0 && colon < 80) {
      title = trimmed.slice(0, colon).trim();
      body = trimmed.slice(colon + 2).trim();
    }
  }

  return (
    <div
      data-kb-card
      className={cn(
        "rounded-md border border-brand-primary/25 bg-brand-tint/50 px-2.5 py-2",
        expanded && "border-brand-primary/45 bg-brand-tint/70",
      )}
    >
      <div className="flex items-start gap-2">
        <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-primary" />
        <div className="min-w-0 flex-1">
          {title && (
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-brand-primary-dark">
              {title}
            </div>
          )}
          {expanded ? (
            <div
              className="max-h-48 overflow-y-auto overscroll-contain whitespace-pre-wrap break-words rounded border border-brand-primary/15 bg-white/80 px-2.5 py-2 text-[12px] leading-relaxed text-brand-navy"
              onWheel={(e) => {
                const el = e.currentTarget;
                const atTop = el.scrollTop <= 0 && e.deltaY < 0;
                const atBottom =
                  el.scrollTop + el.clientHeight >= el.scrollHeight - 1 && e.deltaY > 0;
                if (!atTop && !atBottom) e.stopPropagation();
              }}
            >
              {body}
            </div>
          ) : (
            <p className="line-clamp-2 break-words text-[12px] leading-relaxed text-brand-navy">{body}</p>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onUse(trimmed)}
              className="rounded border border-brand-primary/40 bg-white px-2 py-0.5 text-[11px] font-semibold text-brand-primary-dark hover:bg-brand-tint"
            >
              Use in reply
            </button>
            {long && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onToggle();
                }}
                className="inline-flex items-center gap-0.5 text-[11px] font-medium text-text-secondary hover:text-brand-primary"
              >
                {expanded ? (
                  <>
                    Show less <ChevronUp className="h-3 w-3" />
                  </>
                ) : (
                  <>
                    Show more <ChevronDown className="h-3 w-3" />
                  </>
                )}
              </button>
            )}
            <span className="ml-auto text-[10px] text-text-muted">KB {index + 1}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Composer({
  thread,
  onTakeOver,
  onReturnToBot,
  onSend,
  onRefreshRag,
  busy = false,
  errorMessage = null,
  ragLoading = false,
  ragError = null,
  includeDraftAnswer = false,
  onIncludeDraftAnswerChange,
}: {
  thread: Thread;
  onTakeOver: () => void;
  onReturnToBot?: () => void;
  onSend: (text: string) => void | Promise<void>;
  onRefreshRag?: () => void;
  busy?: boolean;
  errorMessage?: string | null;
  ragLoading?: boolean;
  ragError?: string | null;
  includeDraftAnswer?: boolean;
  onIncludeDraftAnswerChange?: (next: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [cannedOpen, setCannedOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { data: cannedResponses = [] } = useCannedResponses();

  const needsClaim =
    !thread.isMine &&
    (thread.status === "bot" || thread.status === "needs_human" || thread.status === "escalated");
  const botHandling = thread.status === "bot" && !thread.isMine;
  const canReturnToBot =
    Boolean(onReturnToBot) &&
    thread.isMine &&
    (thread.status === "assigned" || thread.status === "needs_human" || thread.status === "escalated");
  const disabled = needsClaim || busy;
  const draft = (thread.ragDraftAnswer || "").trim();
  const takeOverLabel = botHandling
    ? "Take over from bot"
    : thread.status === "escalated"
      ? "Take over escalated thread"
      : "Take over to reply";

  useEffect(() => {
    setText("");
    setCannedOpen(false);
    setEmojiOpen(false);
    setExpandedIdx(null);
  }, [thread.id]);

  const ragFingerprint = thread.ragSuggestions.map((s) => s.slice(0, 64)).join("|");
  useEffect(() => {
    setExpandedIdx(null);
  }, [ragFingerprint]);

  const insertSuggestion = (value: string) => {
    setText((t) => (t ? `${t.trim()}\n\n${value}` : value));
    toast.success(needsClaim ? "Inserted — take over to send" : "Suggestion inserted");
  };

  const insertEmoji = (emoji: string) => {
    setText((t) => `${t}${emoji}`);
  };

  const onPickFile = async (file: File | null) => {
    if (!file) return;
    if (file.size > 200_000) {
      toast.error("File too large for inline paste (max ~200KB). Summarize or paste text instead.");
      return;
    }
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".txt") || lower.endsWith(".md") || lower.endsWith(".csv")) {
      try {
        const body = await file.text();
        const snippet = body.trim().slice(0, 1500);
        setText((t) =>
          t ? `${t.trim()}\n\n📎 ${file.name}\n${snippet}` : `📎 ${file.name}\n${snippet}`,
        );
        toast.success(`Attached text from ${file.name}`);
      } catch {
        toast.error("Could not read that file");
      }
      return;
    }
    setText((t) => (t ? `${t.trim()} 📎 ${file.name}` : `📎 ${file.name}`));
    toast.message("Filename noted in reply — binary WhatsApp attachments aren’t enabled yet");
  };

  const submit = async () => {
    if (!text.trim() || disabled) return;
    const payload = text.trim();
    await onSend(payload);
    setText("");
  };

  const anyExpanded = expandedIdx != null;

  return (
    <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-card">
      <div className="space-y-2.5 border-b border-[var(--border-token)] px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
            <Sparkles className="h-3.5 w-3.5 text-brand-primary" />
            RAG suggestions
          </span>
          <label className="inline-flex h-6 items-center gap-1.5 text-[11.5px] text-text-secondary">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 rounded border-[var(--border-token)] accent-[var(--brand-primary,#2563eb)]"
              checked={includeDraftAnswer}
              onChange={(e) => onIncludeDraftAnswerChange?.(e.target.checked)}
              disabled={ragLoading || !onIncludeDraftAnswerChange}
            />
            Drafted answer
          </label>
          <div className="ml-auto flex min-h-[20px] items-center gap-2">
            {ragLoading ? (
              <span className="inline-flex items-center gap-1.5 text-[11.5px] text-text-muted">
                <RefreshCw className="h-3 w-3 animate-spin" />
                Refreshing from knowledge base…
              </span>
            ) : (
              onRefreshRag && (
                <button
                  type="button"
                  onClick={onRefreshRag}
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] font-medium text-text-secondary hover:bg-surface-sunken hover:text-brand-primary"
                >
                  <RefreshCw className="h-3 w-3" />
                  Refresh
                </button>
              )
            )}
          </div>
        </div>

        {includeDraftAnswer && draft && !ragLoading && (
          <button
            type="button"
            onClick={() => insertSuggestion(draft)}
            className="w-full rounded-md border border-brand-primary/30 bg-brand-tint/40 px-3 py-2.5 text-left hover:border-brand-primary hover:bg-brand-tint/70"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-brand-primary-dark">
              Drafted answer · click to insert
            </div>
            <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-brand-navy">
              {draft}
            </div>
          </button>
        )}

        {includeDraftAnswer && !draft && !ragLoading && !ragError && (
          <div className="rounded-md border border-dashed border-[var(--border-token)] bg-surface-sunken/60 px-3 py-2 text-[12px] text-text-secondary">
            No drafted answer yet for this turn. Suggestions below are KB snippets you can insert.
          </div>
        )}

        <div
          ref={listRef}
          className={cn(
            "flex min-w-0 flex-col gap-2 overflow-y-auto overscroll-contain pr-1 transition-[max-height]",
            // Room for ~2–3 collapsed tiles; grows when a tile is expanded.
            anyExpanded ? "max-h-[min(42vh,360px)]" : "max-h-[min(28vh,220px)]",
          )}
        >
          {thread.ragSuggestions.length === 0 && !ragLoading && !ragError && !draft && (
            <span className="text-[11.5px] text-text-muted">No KB hits yet for this thread.</span>
          )}
          {thread.ragSuggestions.map((s, i) => (
            <SuggestionCard
              key={`${thread.id}-kb-${i}`}
              text={s}
              index={i}
              expanded={expandedIdx === i}
              onUse={insertSuggestion}
              onToggle={() => {
                setExpandedIdx((cur) => (cur === i ? null : i));
                // After expand, keep the card reachable inside the taller scroll box.
                requestAnimationFrame(() => {
                  listRef.current?.querySelectorAll("[data-kb-card]")?.[i]?.scrollIntoView({
                    block: "nearest",
                    behavior: "smooth",
                  });
                });
              }}
            />
          ))}
        </div>
      </div>

      {ragError && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-[12px] text-amber-800">
          {ragError}
        </div>
      )}

      {cannedOpen && (
        <div className="border-b border-[var(--border-token)] bg-surface-sunken px-4 py-2.5">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
            Canned responses
          </div>
          <div className="flex flex-wrap gap-1.5">
            {cannedResponses.length === 0 && (
              <span className="text-[12px] text-text-secondary">No canned responses configured.</span>
            )}
            {cannedResponses.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setText(c.text);
                  setCannedOpen(false);
                }}
                className="rounded-md border border-[var(--border-token)] bg-white px-2.5 py-1 text-[12px] text-text-primary hover:border-brand-primary hover:text-brand-primary-dark"
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {emojiOpen && (
        <div className="border-b border-[var(--border-token)] bg-surface-sunken px-4 py-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
              Insert emoji
            </span>
            <button
              type="button"
              onClick={() => setEmojiOpen(false)}
              className="text-[11px] font-medium text-text-secondary hover:text-brand-primary"
            >
              Close
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {EMOJIS.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => insertEmoji(e)}
                disabled={disabled}
                className="grid h-9 w-9 place-items-center rounded-md bg-white text-lg hover:bg-brand-tint disabled:opacity-50"
                aria-label={`Insert ${e}`}
              >
                {e}
              </button>
            ))}
          </div>
        </div>
      )}

      {needsClaim && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-primary/20 bg-brand-tint/60 px-4 py-2.5">
          <p className="text-[12.5px] text-brand-navy">
            {botHandling
              ? "Bot is handling this thread. Take over to reply on WhatsApp."
              : "This thread needs an agent. Take over to reply."}
          </p>
          <button
            type="button"
            onClick={onTakeOver}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-2 rounded-md bg-brand-primary px-3.5 py-1.5 text-[13px] font-semibold text-white shadow-sm transition-transform hover:bg-brand-primary-hover active:scale-[0.98] disabled:opacity-60"
          >
            {takeOverLabel}
          </button>
        </div>
      )}

      <div className="flex items-end gap-2 px-4 py-3">
        {canReturnToBot && (
          <button
            type="button"
            onClick={onReturnToBot}
            disabled={busy}
            title="Hand this thread back to the bot"
            className="shrink-0 rounded-md border border-[var(--border-token)] bg-white px-2.5 py-2 text-[11.5px] font-semibold text-text-secondary hover:border-brand-primary hover:text-brand-primary-dark disabled:opacity-60"
          >
            Return to bot
          </button>
        )}
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".txt,.md,.csv,image/*,.pdf"
          onChange={(e) => {
            void onPickFile(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="grid h-9 w-9 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken disabled:opacity-50"
          aria-label="Attach file"
          title="Attach text/image note"
        >
          <Paperclip className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => {
            setEmojiOpen(false);
            setCannedOpen((o) => !o);
          }}
          disabled={disabled}
          className={cn(
            "grid h-9 w-9 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken disabled:opacity-50",
            cannedOpen && "bg-surface-sunken text-brand-primary",
          )}
          aria-label="Canned responses"
          title="Canned responses"
        >
          <ChevronUp className="h-4 w-4" />
        </button>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={needsClaim ? "Take over to reply on WhatsApp…" : "Reply on WhatsApp…"}
          rows={1}
          disabled={disabled}
          className="min-h-[40px] max-h-40 flex-1 resize-none rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 py-2 text-[13.5px] placeholder:text-text-muted focus:border-brand-primary focus:bg-white focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => {
            setCannedOpen(false);
            setEmojiOpen((o) => !o);
          }}
          disabled={disabled}
          className={cn(
            "grid h-9 w-9 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken disabled:opacity-50",
            emojiOpen && "bg-surface-sunken text-brand-primary",
          )}
          aria-label="Emoji"
          aria-expanded={emojiOpen}
          title="Insert emoji"
        >
          <Smile className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!text.trim() || disabled}
          className="inline-flex h-9 items-center gap-1.5 rounded-md bg-brand-primary px-3 text-[13px] font-semibold text-white transition-colors hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
        >
          Send
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
      {errorMessage && (
        <div className="border-t border-danger/20 bg-danger-bg px-4 py-2 text-[12.5px] text-danger">
          {errorMessage}
        </div>
      )}
    </div>
  );
}
