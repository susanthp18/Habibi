import { useEffect, useRef, useState } from "react";
import {
  FileImage,
  FileText,
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
import type { Thread } from "@/api/types/inbox";
import { channelMeta, getThreadHandoffState, type InboxRights } from "@/components/inbox/meta";
import { closesAtWords, inboxErrorWords, replyBlockedWords } from "@/components/inbox/inbox-words";
import { ingestInboxDocument, useCannedResponses } from "@/api/inbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const EMOJIS = [
  "👍",
  "🙏",
  "✅",
  "🙂",
  "😮",
  "😂",
  "📎",
  "₹",
  "⏰",
  "✔️",
  "❗",
  "👋",
  "🤝",
  "💯",
  "⚠️",
];

/** Reply states that no wait will clear on this thread: the composer is closed, not just Send. */
const CLOSED_FOR_GOOD = new Set(["channel_not_supported", "whatsapp_window_closed"]);

/** What "Suggest reply" came back with. */
export type SuggestedReply =
  | { kind: "draft"; text: string }
  /** The customer wrote again while it was drafted: it answers the earlier message. */
  | { kind: "superseded" }
  /** The knowledge base or the model could not be reached. */
  | { kind: "failed" }
  /** The knowledge base has nothing that answers them. */
  | { kind: "none" };

function append(current: string, addition: string) {
  return current.trim() ? `${current.trim()}\n\n${addition}` : addition;
}

function SourceCard({
  text,
  onInsert,
  index,
  expanded,
  onToggle,
  disabled,
}: {
  text: string;
  onInsert: (value: string) => void;
  index: number;
  expanded: boolean;
  onToggle: () => void;
  disabled: boolean;
}) {
  const trimmed = text.trim();
  const long = trimmed.length > 160;
  const splitAt = trimmed.indexOf("\n\n");
  let title: string | null = null;
  let body = trimmed;
  if (splitAt > 0 && splitAt < 160) {
    title = trimmed.slice(0, splitAt).trim();
    body = trimmed.slice(splitAt + 2).trim();
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
            <div className="mb-050 text-body-small font-semibold text-text-brand">{title}</div>
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
            <p className="line-clamp-2 break-words text-body-small leading-relaxed text-text">
              {body}
            </p>
          )}
          <div className="mt-075 flex flex-wrap items-center gap-100">
            {/* Evidence, not an answer: this is the knowledge base's own text,
                written for staff. Inserting it is a deliberate act. */}
            <button
              type="button"
              disabled={disabled}
              onClick={() => onInsert(body)}
              title="Insert this passage, as written, into your reply"
              className="focus-ring rounded border border-border-brand/40 bg-surface px-100 py-025 text-body-small font-semibold text-text-brand hover:bg-background-brand-subtlest disabled:opacity-50"
            >
              Insert passage
            </button>
            {long && (
              <button
                type="button"
                onClick={onToggle}
                aria-expanded={expanded}
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
            <span className="ml-auto text-body-small text-text-subtlest">Source {index + 1}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Composer({
  thread,
  rights,
  draft,
  onDraftChange,
  onSend,
  onRefreshRag,
  onSuggestReply,
  ragSuggestions,
  ragLoading,
  ragError,
  ragStale,
  ragSearched,
  busy,
  errorMessage,
}: {
  thread: Thread;
  rights: InboxRights;
  /** This thread's unsent reply. The page owns it, and clears what was sent. */
  draft: string;
  onDraftChange: (next: string | ((current: string) => string)) => void;
  /** Resolves true once the server has queued it. The page keys the attempt. */
  onSend: (text: string) => Promise<boolean>;
  onRefreshRag: () => void;
  /** A reply drafted for the customer's latest message, checked still to be the latest. */
  onSuggestReply: () => Promise<SuggestedReply>;
  ragSuggestions: string[];
  ragLoading: boolean;
  ragError: string | null;
  /** Why the passages shown may not fit: the search failed, or the customer wrote since. */
  ragStale: "search_failed" | "customer_wrote" | null;
  ragSearched: boolean;
  busy: boolean;
  errorMessage: string | null;
}) {
  const text = draft;
  const setText = onDraftChange;
  const [panel, setPanel] = useState<"canned" | "emoji" | null>(null);
  const [cannedFilter, setCannedFilter] = useState("");
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [drafting, setDrafting] = useState(false);
  const textFileRef = useRef<HTMLInputElement>(null);
  const imageFileRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // `data = []` on failure is the graceful-degradation lie: an outage rendered
  // as "No canned responses configured", a claim about the tenant's setup.
  const {
    data: cannedResponses = [],
    isPending: cannedPending,
    isError: cannedFailed,
  } = useCannedResponses();

  const channel = channelMeta[thread.channel].label;
  const { needsClaim } = getThreadHandoffState(thread, rights);
  const ctx = thread.context;
  const blockedReason = ctx.canReply ? null : (ctx.replyBlockedReason ?? "refused");
  const closed = Boolean(blockedReason && CLOSED_FOR_GOOD.has(blockedReason));
  const inputDisabled = needsClaim || !rights.canWrite || closed;
  const canSend = !inputDisabled && !blockedReason && !busy && Boolean(text.trim());
  const hasCustomerMessage = (thread.messages ?? []).some(
    (m) => "sender" in m && m.sender === "customer",
  );

  // Escape closes an open panel.
  useEffect(() => {
    if (!panel) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setPanel(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [panel]);

  const ragFingerprint = ragSuggestions.map((s) => s.slice(0, 64)).join("|");
  useEffect(() => {
    setExpandedIdx(null);
  }, [ragFingerprint]);

  const insert = (value: string, what: string) => {
    setText((t) => append(t, value));
    toast.success(needsClaim ? `${what} inserted — take over to send` : `${what} inserted`);
  };

  const handleSuggestReply = async () => {
    setDrafting(true);
    try {
      const reply = await onSuggestReply();
      if (reply.kind === "draft") insert(reply.text, "Drafted reply");
      else if (reply.kind === "superseded")
        toast.message("The customer wrote again while it was drafted — ask for a new one.");
      else if (reply.kind === "failed")
        toast.error("Couldn’t draft a reply just now. Try again in a moment.");
      else toast.message("The knowledge base has nothing to answer this with.");
    } finally {
      setDrafting(false);
    }
  };

  const pasteFileText = async (file: File | null) => {
    if (!file) return;
    if (file.size > 200_000) {
      toast.error("That file is too large to paste (max 200 KB).");
      return;
    }
    try {
      const body = (await file.text()).trim().slice(0, 1500);
      setText((t) => append(t, body));
    } catch {
      toast.error("Could not read that file.");
    }
  };

  const fileDocument = async (file: File | null) => {
    if (!file) return;
    try {
      const row = await ingestInboxDocument(thread.customerId, file, thread.id);
      // Filed, not sent: nothing in the reply claims an attachment.
      toast.success(
        `Filed to ${thread.customer}'s documents${row.documentRequestId ? ` as ${row.documentRequestId}` : ""}. It was not sent to the customer.`,
      );
    } catch (err) {
      toast.error(inboxErrorWords(err, thread.channel));
    }
  };

  const submit = () => {
    const payload = text.trim();
    // A failure is shown once, in the banner below; the text stays for a retry.
    if (canSend && payload) void onSend(payload);
  };

  const anyExpanded = expandedIdx != null;
  const sourceCount = ragSuggestions.length;
  const visibleCanned = cannedResponses.filter((c) =>
    `${c.label} ${c.text}`.toLowerCase().includes(cannedFilter.trim().toLowerCase()),
  );

  return (
    <div className="shrink-0 border-t border-border bg-surface">
      <div className="flex items-center gap-100 px-200 py-100">
        <button
          type="button"
          onClick={() => void handleSuggestReply()}
          disabled={drafting || inputDisabled || !hasCustomerMessage}
          className="focus-ring inline-flex h-300 items-center gap-075 rounded-medium bg-background-brand-subtlest px-150 text-body-small font-semibold text-text-brand hover:bg-background-brand-subtlest/80 disabled:opacity-60"
        >
          {drafting ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          {drafting ? "Drafting…" : "Suggest reply"}
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
          aria-controls="inbox-sources"
        >
          <BookOpen className="h-3.5 w-3.5" />
          Sources{sourceCount > 0 ? ` (${sourceCount})` : ""}
        </button>
        <div className="ml-auto flex items-center gap-100">
          <button
            type="button"
            onClick={onRefreshRag}
            hidden={!rights.canWrite}
            disabled={ragLoading || !hasCustomerMessage}
            className="focus-ring inline-flex items-center gap-050 rounded px-075 py-025 text-body-small font-medium text-text-subtle hover:bg-surface-sunken hover:text-text-brand disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3 w-3", ragLoading && "animate-spin")} />
            {ragLoading ? "Searching…" : "Refresh"}
          </button>
        </div>
      </div>

      {sourcesOpen && (
        <div id="inbox-sources" className="space-y-100 border-t border-border px-200 py-150">
          {ragStale && (
            <p className="text-body-small text-text-warning">
              {ragStale === "customer_wrote"
                ? "The customer has written since — these answer their earlier message."
                : "Couldn’t search the knowledge base just now — these are from the last search."}
            </p>
          )}
          <div
            ref={listRef}
            className={cn(
              "flex min-w-0 flex-col gap-100 overflow-y-auto overscroll-contain pr-050",
              anyExpanded ? "max-h-[min(32vh,16rem)]" : "max-h-[min(22vh,11rem)]",
            )}
          >
            {sourceCount === 0 && !ragError && (
              <span className="text-body-small text-text-subtlest">
                {!hasCustomerMessage
                  ? "Sources appear once the customer has written."
                  : ragLoading || !ragSearched
                    ? "Searching the knowledge base…"
                    : "No knowledge-base passage matches the customer’s latest message."}
              </span>
            )}
            {ragSuggestions.map((s, i) => (
              <SourceCard
                key={`${thread.id}-kb-${i}`}
                text={s}
                index={i}
                disabled={inputDisabled}
                expanded={expandedIdx === i}
                onInsert={(v) => insert(v, "Passage")}
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

      {panel === "canned" && (
        <div id="inbox-canned" className="border-t border-border bg-surface-sunken px-200 py-150">
          <div className="mb-075 flex items-center justify-between gap-100">
            <span className="text-body-small font-semibold text-text-subtlest">
              Canned responses
            </span>
            {cannedResponses.length > 6 && (
              <input
                value={cannedFilter}
                onChange={(e) => setCannedFilter(e.target.value)}
                aria-label="Filter canned responses"
                placeholder="Filter…"
                className="focus-ring h-300 w-40 rounded-medium border border-border-input bg-surface px-100 text-body-small"
              />
            )}
            <button
              type="button"
              onClick={() => setPanel(null)}
              className="ml-auto text-body-small font-medium text-text-subtle hover:text-text-brand"
            >
              Close
            </button>
          </div>
          <div className="flex max-h-40 flex-wrap gap-075 overflow-y-auto">
            {cannedFailed ? (
              <span className="text-body-small text-text-danger">
                Could not load canned responses. They may still be configured — retry in a moment.
              </span>
            ) : cannedPending ? (
              <span className="text-body-small text-text-subtle">Loading canned responses…</span>
            ) : cannedResponses.length === 0 ? (
              <span className="text-body-small text-text-subtle">
                No canned responses configured.
              </span>
            ) : null}
            {visibleCanned.map((c) => (
              <button
                key={c.id}
                type="button"
                disabled={inputDisabled}
                title={c.text}
                onClick={() => {
                  // Added to what is written, never replacing it.
                  setText((t) => append(t, c.text));
                  setPanel(null);
                }}
                className="rounded-medium border border-border bg-surface px-150 py-050 text-body-small text-text hover:border-border-brand hover:text-text-brand disabled:opacity-50"
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {panel === "emoji" && (
        <div id="inbox-emoji" className="border-t border-border bg-surface-sunken px-200 py-150">
          <div className="mb-075 flex items-center justify-between">
            <span className="text-body-small font-semibold text-text-subtlest">Insert emoji</span>
            <button
              type="button"
              onClick={() => setPanel(null)}
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
                onClick={() => setText((t) => `${t}${e}`)}
                disabled={inputDisabled}
                className="focus-ring grid h-400 w-400 place-items-center rounded-medium bg-surface text-lg hover:bg-background-brand-subtlest disabled:opacity-50"
                aria-label={`Insert ${e}`}
              >
                {e}
              </button>
            ))}
          </div>
        </div>
      )}

      {blockedReason && !needsClaim && (
        <div
          role="status"
          className="border-t border-border-warning-subtle bg-background-warning-subtler px-200 py-075 text-body-small text-text-warning-bolder"
        >
          {replyBlockedWords(blockedReason, thread.channel)}
        </div>
      )}
      {!blockedReason && ctx.replyWindowEndsAt && !needsClaim && (
        <div className="border-t border-border px-200 py-050 text-body-small text-text-subtlest">
          WhatsApp reply window open until {closesAtWords(ctx.replyWindowEndsAt)}.
        </div>
      )}

      <div className="flex items-end gap-100 border-t border-border px-200 py-150">
        <input
          ref={textFileRef}
          type="file"
          className="hidden"
          accept=".txt,.md,.csv,text/plain"
          onChange={(e) => {
            void pasteFileText(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        <input
          ref={imageFileRef}
          type="file"
          className="hidden"
          accept="image/*"
          onChange={(e) => {
            void fileDocument(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        {/* Two different acts, named for what they do. Nothing here sends a
            file to the customer: the reply API carries text only. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              disabled={inputDisabled}
              className="focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50"
              aria-label="Add from a file"
              title="Add from a file"
            >
              <Paperclip className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => textFileRef.current?.click()}>
              <FileText className="h-3.5 w-3.5" />
              Paste text from a file…
            </DropdownMenuItem>
            {rights.canFileDocuments && (
              <DropdownMenuItem onSelect={() => imageFileRef.current?.click()}>
                <FileImage className="h-3.5 w-3.5" />
                File a document image to the customer…
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <button
          type="button"
          onClick={() => setPanel((p) => (p === "canned" ? null : "canned"))}
          disabled={inputDisabled}
          className={cn(
            "focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50",
            panel === "canned" && "bg-surface-sunken text-text-brand",
          )}
          aria-label="Canned responses"
          aria-expanded={panel === "canned"}
          aria-controls="inbox-canned"
          title="Canned responses"
        >
          <MessageSquareText className="h-4 w-4" />
        </button>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // An input method's Enter commits the composed word -- routine for
            // Hindi, Marathi or Tamil -- and must not send the half-typed reply.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          aria-label={`Reply on ${channel}`}
          placeholder={needsClaim ? `Take over to reply on ${channel}…` : `Reply on ${channel}…`}
          rows={1}
          disabled={inputDisabled}
          className="min-h-500 max-h-40 flex-1 resize-none rounded-medium border border-border bg-surface-sunken px-150 py-100 text-body [field-sizing:content] placeholder:text-text-subtlest focus:border-border-brand focus:bg-surface focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => setPanel((p) => (p === "emoji" ? null : "emoji"))}
          disabled={inputDisabled}
          className={cn(
            "focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50",
            panel === "emoji" && "bg-surface-sunken text-text-brand",
          )}
          aria-label="Emoji"
          aria-expanded={panel === "emoji"}
          aria-controls="inbox-emoji"
          title="Insert emoji"
        >
          <Smile className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={!canSend}
          className="focus-ring inline-flex h-400 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse transition-colors hover:bg-background-brand-bold-hovered disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
        >
          {busy ? "Sending…" : "Send"}
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
      {errorMessage && (
        <div
          role="alert"
          className="border-t border-border-danger/20 bg-background-danger px-200 py-100 text-body-small text-text-danger-bolder"
        >
          {errorMessage}
        </div>
      )}
    </div>
  );
}
