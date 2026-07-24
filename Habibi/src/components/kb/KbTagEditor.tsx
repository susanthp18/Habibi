import { useState } from "react";
import { Input } from "@/components/ui/input";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const KB_TAG_SUGGESTIONS = [
  "hdfc",
  "car",
  "home",
  "travel",
  "maid",
  "health",
  "ncd",
  "policy",
  "benefits",
  "faq",
  "upsell",
  "cross-sell",
  "claims",
  "premium",
  "coverage",
  "exclusion",
];

function normalizeTag(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/^#+/, "")
    .replace(/\s+/g, "-")
    .slice(0, 40);
}

export function KbTagEditor({
  tags,
  onChange,
  suggestions = KB_TAG_SUGGESTIONS,
  disabled = false,
  className,
}: {
  tags: string[];
  onChange: (next: string[]) => void;
  suggestions?: string[];
  disabled?: boolean;
  className?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const tag = normalizeTag(raw);
    if (!tag || tags.includes(tag)) {
      setDraft("");
      return;
    }
    onChange([...tags, tag]);
    setDraft("");
  };

  const remove = (tag: string) => {
    onChange(tags.filter((t) => t !== tag));
  };

  const unusedSuggestions = suggestions.filter((s) => !tags.includes(s)).slice(0, 10);

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-[var(--border-token)] bg-surface-sunken/40 px-2 py-1.5">
        {tags.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-1 rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark"
          >
            #{t}
            <button
              type="button"
              disabled={disabled}
              onClick={() => remove(t)}
              className="rounded-full p-0.5 hover:bg-brand-primary/15 disabled:opacity-40"
              aria-label={`Remove ${t}`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <Input
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(draft);
            } else if (e.key === "Backspace" && !draft && tags.length) {
              remove(tags[tags.length - 1]);
            }
          }}
          onBlur={() => {
            if (draft.trim()) add(draft);
          }}
          placeholder={tags.length ? "Add tag…" : "Type a tag and press Enter"}
          className="h-7 min-w-[140px] flex-1 border-0 bg-transparent px-1 shadow-none focus-visible:ring-0"
        />
      </div>
      {unusedSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {unusedSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              disabled={disabled}
              onClick={() => add(s)}
              className="rounded-full border border-dashed border-[var(--border-token)] px-2 py-0.5 text-[10px] text-text-secondary hover:border-brand-primary/40 hover:text-brand-primary-dark disabled:opacity-40"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
