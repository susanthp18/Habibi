import { useMemo, useState } from "react";
import { toast } from "sonner";
import { BookOpen, Bot, ChevronDown, ChevronUp, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { INTENTS, type UnansweredQuestion } from "@/data/bot-analytics-seed";

type SortKey = "hits" | "lastSeen";

export function UnansweredTable({ questions }: { questions: UnansweredQuestion[] }) {
  const [sort, setSort] = useState<SortKey>("hits");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  const rows = useMemo(() => {
    const arr = [...questions];
    arr.sort((a, b) => {
      const va = sort === "hits" ? a.hits : Date.parse(a.lastSeen);
      const vb = sort === "hits" ? b.hits : Date.parse(b.lastSeen);
      return dir === "desc" ? vb - va : va - vb;
    });
    return arr;
  }, [questions, sort, dir]);

  const toggle = (k: SortKey) => {
    if (sort === k) setDir(dir === "desc" ? "asc" : "desc");
    else { setSort(k); setDir("desc"); }
  };

  const intentLabel = (id: string) => INTENTS.find((i) => i.id === id)?.label ?? id;

  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-3 py-2">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[13px] font-semibold text-brand-navy">Top unanswered / RAG-miss questions</div>
            <div className="text-[11px] text-text-muted">Each row is a candidate for Knowledge Base or Prompt Studio work</div>
          </div>
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
            {rows.filter((r) => !r.hasKbDoc).length} without KB coverage
          </span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-muted">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Question</th>
              <th className="px-3 py-2 text-left font-medium">
                <button onClick={() => toggle("hits")} className="inline-flex items-center gap-1 hover:text-brand-primary">
                  Hits {sort === "hits" && (dir === "desc" ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />)}
                </button>
              </th>
              <th className="px-3 py-2 text-left font-medium">Top intent</th>
              <th className="px-3 py-2 text-left font-medium">KB coverage</th>
              <th className="px-3 py-2 text-left font-medium">
                <button onClick={() => toggle("lastSeen")} className="inline-flex items-center gap-1 hover:text-brand-primary">
                  Last seen {sort === "lastSeen" && (dir === "desc" ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />)}
                </button>
              </th>
              <th className="px-3 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-token)]">
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-surface-sunken">
                <td className="px-3 py-2 text-text-primary">{r.text}</td>
                <td className="px-3 py-2 font-semibold text-brand-navy tabular-nums">{r.hits}</td>
                <td className="px-3 py-2 text-text-secondary">{intentLabel(r.topIntent)}</td>
                <td className="px-3 py-2">
                  {r.hasKbDoc ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
                      <CheckCircle2 className="h-3 w-3" /> Doc exists
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                      <AlertTriangle className="h-3 w-3" /> Missing
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-text-secondary">{r.lastSeen}</td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-1">
                    <button
                      onClick={() => toast.success("Sent to Knowledge Base", { description: "Added as suggested doc gap." })}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]",
                        r.suggestedFix !== "prompt"
                          ? "border-brand-primary bg-brand-tint text-brand-primary-dark hover:bg-brand-tint-strong"
                          : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                      )}
                    >
                      <BookOpen className="h-3 w-3" /> Add to KB
                    </button>
                    <button
                      onClick={() => toast.success("Sent to Prompt Studio", { description: "Draft prompt-fix task created." })}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]",
                        r.suggestedFix !== "kb"
                          ? "border-brand-primary bg-brand-tint text-brand-primary-dark hover:bg-brand-tint-strong"
                          : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                      )}
                    >
                      <Bot className="h-3 w-3" /> Prompt fix
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-text-muted">
                  No unanswered questions recorded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
