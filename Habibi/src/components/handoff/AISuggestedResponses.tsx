import { useState } from "react";
import { BookOpen, Check, Copy, Sparkles } from "lucide-react";
import type { HandoffSuggestion } from "@/api/handoff";
import { Lozenge } from "@/components/ui/lozenge";
import { copyText } from "./handoff-words";

type Canned = { id: string; label: string; text: string };

type Props = {
  items: HandoffSuggestion[];
  /** A persisted suggestion the agent copied: recorded as used. */
  onUsed?: (id: string) => void;
  canned?: Canned[];
  /** The canned list failed to load (not "there are none"). */
  cannedFailed?: boolean;
};

export function AISuggestedResponses({ items, onUsed, canned = [], cannedFailed }: Props) {
  const open = items.filter((s) => !s.accepted);
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <h2 className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" />
          Suggested responses
        </h2>
        <Lozenge tone="neutral">{open.length}</Lozenge>
      </div>
      <ul className="divide-y divide-border">
        {open.length === 0 && (
          <li className="px-150 py-200 text-center text-body-small text-text-subtlest">
            No suggestions for this case.
          </li>
        )}
        {open.map((s) => (
          <SuggestionRow key={s.id} s={s} onUsed={onUsed} />
        ))}
      </ul>
      {(canned.length > 0 || cannedFailed) && (
        <div className="border-t border-border px-150 py-100">
          <h3 className="mb-075 flex items-center gap-075 text-body-small font-semibold text-text-subtle">
            <BookOpen className="h-3.5 w-3.5" />
            Playbooks
          </h3>
          {cannedFailed ? (
            <p className="text-body-small text-text-subtlest">Couldn't load the playbooks.</p>
          ) : (
            <ul className="space-y-050">
              {canned.slice(0, 4).map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => void copyText(c.text)}
                    title={c.text}
                    className="flex w-full items-center gap-075 truncate rounded-medium px-075 py-050 text-left text-body-small text-text hover:bg-surface-sunken"
                  >
                    <Copy className="h-3 w-3 shrink-0 text-text-subtlest" />
                    <span className="truncate">{c.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function SuggestionRow({ s, onUsed }: { s: HandoffSuggestion; onUsed?: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const long = s.body.length > 180;
  return (
    <li className="px-150 py-150">
      <div className="flex items-center gap-075">
        <span className="text-body-small font-semibold text-text">{s.title}</span>
        {s.stale ? (
          <Lozenge tone="warning" title="Found for an earlier customer message">
            Earlier message
          </Lozenge>
        ) : null}
      </div>
      <p
        className={
          expanded || !long
            ? "mt-050 whitespace-pre-wrap text-body-small leading-snug text-text-subtle"
            : "mt-050 line-clamp-3 text-body-small leading-snug text-text-subtle"
        }
      >
        {s.body}
      </p>
      {long ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-025 text-body-small font-medium text-text-brand hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      ) : null}
      <div className="mt-100 flex items-center justify-between">
        <span className="text-body-small text-text-subtlest">{s.source}</span>
        <button
          type="button"
          onClick={() =>
            void copyText(s.body).then((ok) => {
              if (!ok) return;
              setCopied(true);
              onUsed?.(s.id);
            })
          }
          className="flex items-center gap-050 rounded-medium border border-border px-100 py-050 text-body-small font-semibold text-text hover:bg-surface-sunken"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </li>
  );
}
