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
  MessageSquareText,
  BookOpen,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread } from "@/data/inbox-seed";
import { getThreadHandoffState } from "@/components/inbox/meta";
import { ingestInboxDocument, useCannedResponses } from "@/api/inbox";

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
        "rounded-medium border border-border-brand/25 bg-background-brand-subtlest/50 px-150 py-100",
        expanded && "border-border-brand/45 bg-background-brand-subtlest/70",
      )}
    >
      <div className="flex items-start gap-100">
        <Zap className="mt-025 h-3.5 w-3.5 shrink-0 text-text-brand" />
        <div className="min-w-0 flex-1">
          {title && (
            <div className="mb-050 text-body-small font-semibold text-text-brand">
              {title}
            </div>
          )}
          {expanded ? (
            <div
              className="max-h-48 overflow-y-auto overscroll-contain whitespace-pre-wrap break-words rounded border border-border-brand/15 bg-surface/80 px-150 py-100 text-body-small leading-relaxed text-text"
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
            <p className="line-clamp-2 break-words text-body-small leading-relaxed text-text">{body}</p>
          )}
          <div className="mt-075 flex flex-wrap items-center gap-100">
            <button
              type="button"
              onClick={() => onUse(trimmed)}
              className="focus-ring rounded border border-border-brand/40 bg-surface px-100 py-025 text-body-small font-semibold text-text-brand hover:bg-background-brand-subtlest"
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
                className="focus-ring inline-flex items-center gap-025 text-body-small font-medium text-text-subtle hover:text-text-brand"
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
            <span className="ml-auto text-body-small text-text-subtlest">KB {index + 1}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Composer({
  thread,
  onSend,
  onRefreshRag,
  onSuggestReply,
  busy = false,
  errorMessage = null,
  ragLoading = false,
  ragError = null,
}: {
  thread: Thread;
  onSend: (text: string) => void | Promise<void>;
  onRefreshRag?: (withDraft?: boolean) => void;
  onSuggestReply?: () => void;
  busy?: boolean;
  errorMessage?: string | null;
  ragLoading?: boolean;
  ragError?: string | null;
}) {
  const [text, setText] = useState("");
  const [cannedOpen, setCannedOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [awaitingDraft, setAwaitingDraft] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const seenSuggestLoading = useRef(false);
  const { data: cannedResponses = [] } = useCannedResponses();

  const { needsClaim } = getThreadHandoffState(thread, false);
  const disabled = needsClaim || busy || sending;
  const draft = (thread.ragDraftAnswer || "").trim();
  const sourceCount = thread.ragSuggestions.length;

  useEffect(() => {
    setText("");
    setCannedOpen(false);
    setEmojiOpen(false);
    setSourcesOpen(false);
    setExpandedIdx(null);
    setAwaitingDraft(false);
    seenSuggestLoading.current = false;
  }, [thread.id]);

  const ragFingerprint = thread.ragSuggestions.map((s) => s.slice(0, 64)).join("|");
  useEffect(() => {
    setExpandedIdx(null);
  }, [ragFingerprint]);

  useEffect(() => {
    if (!awaitingDraft) return;
    if (ragLoading) {
      seenSuggestLoading.current = true;
      return;
    }
    if (!seenSuggestLoading.current) return;
    seenSuggestLoading.current = false;
    setAwaitingDraft(false);
    if (draft) {
      setText((t) => (t ? `${t.trim()}\n\n${draft}` : draft));
      toast.success(needsClaim ? "Draft inserted — take over to send" : "Draft inserted");
    }
  }, [awaitingDraft, ragLoading, draft, needsClaim]);

  const insertSuggestion = (value: string) => {
    setText((t) => (t ? `${t.trim()}\n\n${value}` : value));
    toast.success(needsClaim ? "Inserted — take over to send" : "Suggestion inserted");
  };

  const insertEmoji = (emoji: string) => {
    setText((t) => `${t}${emoji}`);
  };

  const handleSuggestReply = () => {
    if (draft && !ragLoading) {
      insertSuggestion(draft);
      return;
    }
    setAwaitingDraft(true);
    seenSuggestLoading.current = ragLoading;
    onSuggestReply?.();
  };

  const onPickFile = async (file: File | null) => {
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".txt") || lower.endsWith(".md") || lower.endsWith(".csv")) {
      if (file.size > 200_000) {
        toast.error("File too large for inline paste (max ~200KB). Summarize or paste text instead.");
        return;
      }
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
    if (file.type.startsWith("image/") && thread.customerId) {
      try {
        const row = await ingestInboxDocument(thread.customerId, file, thread.id);
        toast.success(
          row.documentRequestId
            ? `Receipt filed as ${row.documentRequestId}`
            : `Receipt filed (${file.name})`,
        );
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Could not file that image");
      }
      return;
    }
    toast.message("Filename noted in reply — binary WhatsApp attachments aren’t enabled yet");
  };

  const submit = async () => {
    if (!text.trim() || disabled) return;
    setSending(true);
    try {
      const payload = text.trim();
      await onSend(payload);
      setText("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not send the message");
    } finally {
      setSending(false);
    }
  };

  const anyExpanded = expandedIdx != null;
  const suggestBusy = ragLoading && awaitingDraft;

  return (
    <div className="shrink-0 border-t border-border bg-surface">
      <div className="flex items-center gap-100 px-200 py-100">
        <button
          type="button"
          onClick={handleSuggestReply}
          disabled={suggestBusy || (!onSuggestReply && !draft)}
          className="focus-ring inline-flex h-300 items-center gap-075 rounded-medium bg-background-brand-subtlest px-150 text-body-small font-semibold text-text-brand hover:bg-background-brand-subtlest/80 disabled:opacity-60"
        >
          {suggestBusy ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          {suggestBusy ? "Drafting…" : "Suggest reply"}
        </button>
        <button
          type="button"
          onClick={() => setSourcesOpen((o) => !o)}
          className={cn(
            "focus-ring inline-flex h-300 items-center gap-075 rounded-medium px-150 text-body-small font-medium",
            sourcesOpen
              ? "bg-surface-sunken text-text-brand"
              : "text-text-subtle hover:bg-surface-sunken hover:text-text-brand",
          )}
          aria-expanded={sourcesOpen}
        >
          <BookOpen className="h-3.5 w-3.5" />
          Sources{sourceCount > 0 ? ` (${sourceCount})` : ""}
        </button>
        <div className="ml-auto flex items-center gap-100">
          {ragLoading && sourcesOpen && !awaitingDraft && (
            <span className="inline-flex items-center gap-075 text-body-small text-text-subtlest">
              <RefreshCw className="h-3 w-3 animate-spin" />
              Refreshing…
            </span>
          )}
          {onRefreshRag && (
            <button
              type="button"
              onClick={() => onRefreshRag(false)}
              disabled={ragLoading}
              className="focus-ring inline-flex items-center gap-050 rounded px-075 py-025 text-body-small font-medium text-text-subtle hover:bg-surface-sunken hover:text-text-brand disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3 w-3", ragLoading && "animate-spin")} />
              Refresh
            </button>
          )}
        </div>
      </div>

      {sourcesOpen && (
        <div className="space-y-100 border-t border-border px-200 py-150">
          <div
            ref={listRef}
            className={cn(
              "flex min-w-0 flex-col gap-100 overflow-y-auto overscroll-contain pr-050",
              anyExpanded ? "max-h-[min(32vh,16rem)]" : "max-h-[min(22vh,11rem)]",
            )}
          >
            {sourceCount === 0 && !ragLoading && !ragError && (
              <span className="text-body-small text-text-subtlest">No KB hits yet for this thread.</span>
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
      )}

      {ragError && (
        <div className="border-t border-border-warning-subtle bg-background-warning-subtler px-200 py-075 text-body-small text-text-warning-bolder">
          {ragError}
        </div>
      )}

      {cannedOpen && (
        <div className="border-t border-border bg-surface-sunken px-200 py-150">
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">
            Canned responses
          </div>
          <div className="flex flex-wrap gap-075">
            {cannedResponses.length === 0 && (
              <span className="text-body-small text-text-subtle">No canned responses configured.</span>
            )}
            {cannedResponses.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setText(c.text);
                  setCannedOpen(false);
                }}
                className="rounded-medium border border-border bg-surface px-150 py-050 text-body-small text-text hover:border-border-brand hover:text-text-brand"
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {emojiOpen && (
        <div className="border-t border-border bg-surface-sunken px-200 py-150">
          <div className="mb-075 flex items-center justify-between">
            <span className="text-body-small font-semibold text-text-subtlest">
              Insert emoji
            </span>
            <button
              type="button"
              onClick={() => setEmojiOpen(false)}
              className="text-body-small font-medium text-text-subtle hover:text-text-brand"
            >
              Close
            </button>
          </div>
          <div className="flex flex-wrap gap-050">
            {EMOJIS.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => insertEmoji(e)}
                disabled={disabled}
                className="focus-ring grid h-400 w-400 place-items-center rounded-medium bg-surface text-lg hover:bg-background-brand-subtlest disabled:opacity-50"
                aria-label={`Insert ${e}`}
              >
                {e}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-end gap-100 border-t border-border px-200 py-150">
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
          className="focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50"
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
            "focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50",
            cannedOpen && "bg-surface-sunken text-text-brand",
          )}
          aria-label="Canned responses"
          title="Canned responses"
        >
          <MessageSquareText className="h-4 w-4" />
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
          className="min-h-500 max-h-40 flex-1 resize-none rounded-medium border border-border bg-surface-sunken px-150 py-100 text-body placeholder:text-text-subtlest focus:border-border-brand focus:bg-surface focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => {
            setCannedOpen(false);
            setEmojiOpen((o) => !o);
          }}
          disabled={disabled}
          className={cn(
            "focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50",
            emojiOpen && "bg-surface-sunken text-text-brand",
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
          className="focus-ring inline-flex h-400 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse transition-colors hover:bg-background-brand-bold-hovered disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
        >
          Send
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
      {errorMessage && (
        <div className="border-t border-border-danger/20 bg-background-danger px-200 py-100 text-body-small text-text-danger-bolder">
          {errorMessage}
        </div>
      )}
    </div>
  );
}
