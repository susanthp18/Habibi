import { useState } from "react";
import { Pin, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { CustomerNote } from "@/data/customer360-seed";
import { fmtRelative } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

export function NotesTab({
  notes,
  onAdd,
}: {
  notes: CustomerNote[];
  onAdd: (text: string) => void;
}) {
  const [text, setText] = useState("");

  return (
    <div className="space-y-200">
      <div className="rounded-large border border-border bg-surface p-150">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a note… (use @teammate to mention)"
          rows={3}
          className="resize-none border-0 bg-transparent p-050 shadow-none focus-visible:ring-0"
        />
        <div className="mt-100 flex items-center justify-between border-t border-border pt-100 text-body-small text-text-subtle">
          <span>Notes are visible to your team · Auditable</span>
          <Button
            size="sm"
            disabled={!text.trim()}
            onClick={() => {
              onAdd(text.trim());
              setText("");
            }}
          >
            <Send className="h-3.5 w-3.5" />
            Save note
          </Button>
        </div>
      </div>

      {notes.length === 0 ? (
        <div className="rounded-large border border-dashed border-border bg-surface p-500 text-center text-sm text-text-subtlest">
          No notes yet. Add one to start the record.
        </div>
      ) : (
        <ul className="space-y-100">
          {[...notes]
            .sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned) || b.at.localeCompare(a.at))
            .map((n) => (
              <li
                key={n.id}
                className={cn(
                  "rounded-large border p-150 text-sm",
                  n.pinned ? "border-border-brand/30 bg-background-brand-subtlest/30" : "border-border bg-surface",
                )}
              >
                <div className="mb-050 flex items-center gap-100 text-xs text-text-subtle">
                  <span className="font-medium text-text">{n.author}</span>
                  <span>· {fmtRelative(n.at)}</span>
                  {n.pinned && (
                    <Lozenge tone="selected">
                      <Pin className="h-2.5 w-2.5" /> Pinned
                    </Lozenge>
                  )}
                </div>
                <p className="whitespace-pre-line text-text">{n.text}</p>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
