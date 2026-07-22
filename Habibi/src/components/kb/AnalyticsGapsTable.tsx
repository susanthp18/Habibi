import { useMemo, useState } from "react";
import { unansweredQuestions } from "@/data/bot-analytics-seed";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { CheckCircle2, MessageSquarePlus, BookOpen } from "lucide-react";

export function AnalyticsGapsTable({
  onCreateFaq,
  onAttachDoc,
}: {
  onCreateFaq: (text: string) => void;
  onAttachDoc: (text: string) => void;
}) {
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  const [showResolved, setShowResolved] = useState(false);

  const rows = useMemo(() => {
    return unansweredQuestions.filter((q) => (showResolved ? true : !resolved.has(q.id)));
  }, [resolved, showResolved]);

  const resolve = (id: string, text: string, kind: "faq" | "doc") => {
    setResolved((s) => new Set(s).add(id));
    if (kind === "faq") onCreateFaq(text);
    else onAttachDoc(text);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[13px] font-medium text-brand-navy">
          Coverage gaps <span className="text-text-muted">(from Bot Analytics)</span>
        </div>
        <label className="flex items-center gap-2 text-[12px] text-text-secondary">
          <Switch checked={showResolved} onCheckedChange={setShowResolved} />
          Show resolved
        </label>
      </div>
      {rows.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
          <CheckCircle2 className="h-8 w-8 text-emerald-500" />
          <div className="text-[13px] font-medium text-brand-navy">
            No open gaps — the bot is fully covered.
          </div>
        </div>
      ) : (
        <table className="w-full text-[13px]">
          <thead className="bg-surface-sunken text-[11px] font-medium uppercase tracking-wide text-text-muted">
            <tr>
              <th className="px-3 py-2 text-left">Unanswered question</th>
              <th className="px-3 py-2 text-right">Hits</th>
              <th className="px-3 py-2 text-left">Top intent</th>
              <th className="px-3 py-2 text-left">Last seen</th>
              <th className="px-3 py-2 text-left">Suggestion</th>
              <th className="px-3 py-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => {
              const done = resolved.has(q.id);
              return (
                <tr
                  key={q.id}
                  className={cn(
                    "border-t border-[var(--border-token)]",
                    done && "opacity-60",
                  )}
                >
                  <td className="px-3 py-2.5 text-text-primary">{q.text}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-text-secondary">
                    {q.hits}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
                      {q.topIntent}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-[12px] text-text-secondary">
                    {new Date(q.lastSeen).toLocaleDateString(undefined, {
                      day: "2-digit",
                      month: "short",
                    })}
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                        q.suggestedFix === "kb"
                          ? "border-brand-primary/30 bg-brand-tint text-brand-primary-dark"
                          : q.suggestedFix === "prompt"
                            ? "border-amber-200 bg-amber-50 text-amber-700"
                            : "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700",
                      )}
                    >
                      {q.suggestedFix === "kb"
                        ? "Add to KB"
                        : q.suggestedFix === "prompt"
                          ? "Fix prompt"
                          : "KB + Prompt"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    {done ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
                        <CheckCircle2 className="h-3.5 w-3.5" /> Resolved
                      </span>
                    ) : (
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => resolve(q.id, q.text, "faq")}
                        >
                          <MessageSquarePlus className="mr-1 h-3 w-3" /> Create FAQ
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => resolve(q.id, q.text, "doc")}
                        >
                          <BookOpen className="mr-1 h-3 w-3" /> Attach doc
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
