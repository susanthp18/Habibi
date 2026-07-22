import { useState } from "react";
import { Pin, Send } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { CustomerNote } from "@/data/customer360-seed";
import { fmtRelative } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

export function NotesTab({
  notes,
  onAdd,
}: {
  notes: CustomerNote[];
  onAdd: (text: string) => void;
}) {
  const [text, setText] = useState("");

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-surface-card p-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a note… (use @teammate to mention)"
          rows={3}
          className="resize-none border-0 bg-transparent p-1 shadow-none focus-visible:ring-0"
        />
        <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-[11px] text-text-secondary">
          <span>Notes are visible to your team · Auditable</span>
          <Button
            size="sm"
            disabled={!text.trim()}
            onClick={() => {
              onAdd(text.trim());
              setText("");
              toast.success("Note added");
            }}
          >
            <Send className="h-3.5 w-3.5" />
            Save note
          </Button>
        </div>
      </div>

      {notes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-surface-card p-10 text-center text-sm text-text-muted">
          No notes yet. Add one to start the record.
        </div>
      ) : (
        <ul className="space-y-2">
          {[...notes]
            .sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned) || b.at.localeCompare(a.at))
            .map((n) => (
              <li
                key={n.id}
                className={cn(
                  "rounded-lg border p-3 text-sm",
                  n.pinned ? "border-brand-primary/30 bg-brand-tint/30" : "border-border bg-surface-card",
                )}
              >
                <div className="mb-1 flex items-center gap-2 text-xs text-text-secondary">
                  <span className="font-medium text-brand-navy">{n.author}</span>
                  <span>· {fmtRelative(n.at)}</span>
                  {n.pinned && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-primary">
                      <Pin className="h-2.5 w-2.5" /> Pinned
                    </span>
                  )}
                </div>
                <p className="whitespace-pre-line text-text-primary">{n.text}</p>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
