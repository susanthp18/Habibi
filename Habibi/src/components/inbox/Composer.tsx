import { useState } from "react";
import {
  Paperclip,
  SendHorizontal,
  Smile,
  Sparkles,
  Zap,
  ChevronUp,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { cannedResponses, type Thread } from "@/data/inbox-seed";

export function Composer({
  thread,
  tookOver,
  onTakeOver,
  onSend,
}: {
  thread: Thread;
  tookOver: boolean;
  onTakeOver: () => void;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const [cannedOpen, setCannedOpen] = useState(false);
  const botHandling = thread.status === "bot" && !tookOver;
  const disabled = botHandling;

  const submit = () => {
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-card">
      {/* RAG suggestions */}
      <div className="flex items-center gap-2 border-b border-[var(--border-token)] px-4 py-2">
        <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
          <Sparkles className="h-3 w-3 text-brand-primary" />
          RAG suggestions
        </span>
        <div className="flex flex-wrap gap-1.5">
          {thread.ragSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                setText((t) => (t ? `${t} ${s}` : s));
                toast("Suggestion inserted");
              }}
              className="inline-flex items-center gap-1 rounded-full border border-brand-primary/30 bg-brand-tint px-2.5 py-1 text-[11.5px] font-medium text-brand-primary-dark hover:border-brand-primary hover:bg-brand-tint/70"
            >
              <Zap className="h-3 w-3" />
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Canned popover */}
      {cannedOpen && (
        <div className="border-b border-[var(--border-token)] bg-surface-sunken px-4 py-2">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
            Canned responses
          </div>
          <div className="flex flex-wrap gap-1.5">
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

      {/* Composer body */}
      <div className="relative flex items-end gap-2 px-4 py-3">
        {disabled && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-white/70 backdrop-blur-[1px]">
            <button
              type="button"
              onClick={onTakeOver}
              className="pointer-events-auto inline-flex items-center gap-2 rounded-md bg-brand-primary px-4 py-2 text-[13px] font-semibold text-white shadow-pop transition-transform hover:bg-brand-primary-hover active:scale-[0.98]"
            >
              Take over from bot
            </button>
          </div>
        )}
        <button
          type="button"
          onClick={() => toast("Attachments coming soon")}
          className="grid h-9 w-9 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken"
          aria-label="Attach"
        >
          <Paperclip className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => setCannedOpen((o) => !o)}
          className={cn(
            "grid h-9 w-9 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken",
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
              submit();
            }
          }}
          placeholder="Reply on WhatsApp…"
          rows={1}
          className="min-h-[40px] max-h-40 flex-1 resize-none rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 py-2 text-[13.5px] placeholder:text-text-muted focus:border-brand-primary focus:bg-white focus:outline-none"
        />
        <button
          type="button"
          onClick={() => toast("Emoji picker coming soon")}
          className="grid h-9 w-9 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken"
          aria-label="Emoji"
        >
          <Smile className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={!text.trim()}
          className="inline-flex h-9 items-center gap-1.5 rounded-md bg-brand-primary px-3 text-[13px] font-semibold text-white transition-colors hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
        >
          Send
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
