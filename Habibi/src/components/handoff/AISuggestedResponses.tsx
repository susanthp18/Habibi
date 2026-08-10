import { Copy, Send, Sparkles } from "lucide-react";
import type { Suggestion } from "@/data/handoff-seed";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  items: Suggestion[];
  onInsert: (s: Suggestion) => void;
};

export function AISuggestedResponses({ items, onInsert }: Props) {
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" />
          AI suggestions
        </div>
        <Lozenge tone="selected">
          {items.length} live
        </Lozenge>
      </div>
      <ul className="divide-y divide-border">
        {items.length === 0 && (
          <li className="px-150 py-300 text-center text-body-small text-text-subtlest">
            Listening… suggestions appear as the conversation develops.
          </li>
        )}
        {items.map((s) => (
          <li key={s.id} className="animate-fade-up px-150 py-150">
            <div className="text-body-small font-semibold text-text">{s.title}</div>
            <p className="mt-050 line-clamp-3 text-body-small leading-snug text-text-subtle">
              {s.body}
            </p>
            <div className="mt-100 flex items-center justify-between">
              <span className="text-body-small text-text-subtlest">{s.source}</span>
              <div className="flex items-center gap-050">
                <button
                  type="button"
                  onClick={() => navigator.clipboard?.writeText(s.body)}
                  title="Copy"
                  className="grid h-7 w-7 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => onInsert(s)}
                  className="flex items-center gap-050 rounded-medium bg-background-brand-bold px-100 py-050 text-body-small font-semibold text-white hover:bg-background-brand-bold-hovered"
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
