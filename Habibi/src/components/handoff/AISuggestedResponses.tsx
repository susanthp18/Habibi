import { Copy, Send, Sparkles } from "lucide-react";
import type { Suggestion } from "@/data/handoff-seed";

type Props = {
  items: Suggestion[];
  onInsert: (s: Suggestion) => void;
};

export function AISuggestedResponses({ items, onInsert }: Props) {
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-brand-navy">
          <Sparkles className="h-3.5 w-3.5 text-brand-primary" />
          AI suggestions
        </div>
        <span className="rounded-full bg-brand-tint px-1.5 py-0.5 text-[10px] font-semibold text-brand-primary-dark">
          {items.length} live
        </span>
      </div>
      <ul className="divide-y divide-[var(--border-token)]">
        {items.length === 0 && (
          <li className="px-3 py-6 text-center text-[12px] text-text-muted">
            Listening… suggestions appear as the conversation develops.
          </li>
        )}
        {items.map((s) => (
          <li key={s.id} className="animate-fade-up px-3 py-2.5">
            <div className="text-[12px] font-semibold text-brand-navy">{s.title}</div>
            <p className="mt-1 line-clamp-3 text-[12px] leading-snug text-text-secondary">
              {s.body}
            </p>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-[10px] text-text-muted">{s.source}</span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => navigator.clipboard?.writeText(s.body)}
                  title="Copy"
                  className="grid h-7 w-7 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => onInsert(s)}
                  className="flex items-center gap-1 rounded-md bg-brand-primary px-2 py-1 text-[11px] font-semibold text-white hover:bg-brand-primary-hover"
                >
                  <Send className="h-3 w-3" />
                  Speak this
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
