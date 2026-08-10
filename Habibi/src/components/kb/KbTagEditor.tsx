import { useState } from "react";
import { Input } from "@/components/ui/input";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

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
    <div className={cn("space-y-100", className)}>
      <div className="flex min-h-9 flex-wrap items-center gap-075 rounded-medium border border-border bg-surface-sunken/40 px-100 py-075 focus-within:border-border-brand/50 focus-within:ring-1 focus-within:ring-border-brand/30">
        {tags.map((t) => (
          <Lozenge
            key={t} tone="selected">
            #{t}
            <button
              type="button"
              disabled={disabled}
              onClick={() => remove(t)}
              className="rounded-full p-025 hover:bg-background-brand-bold/15 disabled:opacity-40"
              aria-label={`Remove ${t}`}
            >
              <X className="h-3 w-3" />
            </button>
          </Lozenge>
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
          className="h-7 min-w-[8.75rem] flex-1 border-0 bg-transparent px-050 shadow-none focus-visible:ring-0"
        />
      </div>
      {unusedSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-050">
          {unusedSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              disabled={disabled}
              onClick={() => add(s)}
              className="rounded-full border border-dashed border-border px-100 py-025 text-body-small text-text-subtle hover:border-border-brand/40 hover:text-text-brand disabled:opacity-40"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
