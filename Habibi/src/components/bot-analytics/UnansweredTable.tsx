import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { BookOpen, Bot, ChevronDown, ChevronUp, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { INTENTS, type UnansweredQuestion } from "@/data/bot-analytics-seed";
import { linkKbGap } from "@/api/kb";
import { usePublishedPromptVersion } from "@/api/prompt-studio";
import { USE_MOCK } from "@/api/config";
import { Lozenge } from "@/components/ui/lozenge";

type SortKey = "hits" | "lastSeen";

export function UnansweredTable({ questions }: { questions: UnansweredQuestion[] }) {
  const navigate = useNavigate();
  const publishedQuery = usePublishedPromptVersion();
  const [sort, setSort] = useState<SortKey>("hits");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [busyId, setBusyId] = useState<string | null>(null);

  const rows = useMemo(() => {
    const arr = [...questions];
    arr.sort((a, b) => {
      if (sort === "hits") return dir === "desc" ? b.hits - a.hits : a.hits - b.hits;
      // Date.parse returns NaN for an unparseable lastSeen, and a comparator
      // that returns NaN leaves the order of the whole array
      // implementation-defined. Sink invalid dates to the end either way.
      const va = Date.parse(a.lastSeen);
      const vb = Date.parse(b.lastSeen);
      const aBad = Number.isNaN(va);
      const bBad = Number.isNaN(vb);
      if (aBad || bBad) return aBad === bBad ? 0 : aBad ? 1 : -1;
      return dir === "desc" ? vb - va : va - vb;
    });
    return arr;
  }, [questions, sort, dir]);

  const toggle = (k: SortKey) => {
    if (sort === k) setDir(dir === "desc" ? "asc" : "desc");
    else {
      setSort(k);
      setDir("desc");
    }
  };

  const intentLabel = (id: string) => INTENTS.find((i) => i.id === id)?.label ?? id;

  const onAddToKb = (r: UnansweredQuestion) => {
    void navigate({
      to: "/knowledge-base",
      search: { gapId: r.id, q: r.text },
    });
  };

  const onPromptFix = async (r: UnansweredQuestion) => {
    setBusyId(r.id);
    try {
      if (!USE_MOCK) {
        let publishedId = publishedQuery.data?.id;
        if (!publishedId) {
          try {
            const fresh = await publishedQuery.refetch();
            publishedId = fresh.data?.id;
          } catch {
            // Fall through — navigate without link if publish lookup fails.
          }
        }
        if (publishedId) {
          try {
            await linkKbGap(r.id, { promptVersionId: publishedId });
          } catch (err) {
            // Navigate anyway — link is audit trail, not a hard gate.
            toast.message("Gap link skipped", {
              description: err instanceof Error ? err.message : "Could not persist prompt link",
            });
          }
        }
      }
      void navigate({
        to: "/prompt-studio",
        search: { unansweredId: r.id, note: r.text },
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-150 py-100">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-body font-semibold text-text">Top unanswered / RAG-miss questions</div>
            <div className="text-body-small text-text-subtlest">Each row is a candidate for Knowledge Base or Prompt Studio work</div>
          </div>
          <Lozenge tone="warning">
            {rows.filter((r) => !r.hasKbDoc).length} without KB coverage
          </Lozenge>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-body-small">
          <thead className="bg-surface-sunken text-body-small text-text-subtlest">
            <tr>
              <th className="px-150 py-100 text-left font-medium">Question</th>
              <th className="px-150 py-100 text-left font-medium">
                <button onClick={() => toggle("hits")} className="inline-flex items-center gap-050 hover:text-text-brand">
                  Hits {sort === "hits" && (dir === "desc" ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />)}
                </button>
              </th>
              <th className="px-150 py-100 text-left font-medium">Top intent</th>
              <th className="px-150 py-100 text-left font-medium">KB coverage</th>
              <th className="px-150 py-100 text-left font-medium">
                <button onClick={() => toggle("lastSeen")} className="inline-flex items-center gap-050 hover:text-text-brand">
                  Last seen {sort === "lastSeen" && (dir === "desc" ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />)}
                </button>
              </th>
              <th className="px-150 py-100 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-surface-sunken">
                <td className="px-150 py-100 text-text">{r.text}</td>
                <td className="px-150 py-100 font-semibold text-text tabular-nums">{r.hits}</td>
                <td className="px-150 py-100 text-text-subtle">{intentLabel(r.topIntent)}</td>
                <td className="px-150 py-100">
                  {r.hasKbDoc ? (
                    <Lozenge tone="success">
                      <CheckCircle2 className="h-3 w-3" /> Doc exists
                    </Lozenge>
                  ) : (
                    <Lozenge tone="warning">
                      <AlertTriangle className="h-3 w-3" /> Missing
                    </Lozenge>
                  )}
                </td>
                <td className="px-150 py-100 text-text-subtle">{r.lastSeen}</td>
                <td className="px-150 py-100">
                  <div className="flex justify-end gap-050">
                    <button
                      onClick={() => onAddToKb(r)}
                      className={cn(
                        "inline-flex items-center gap-050 rounded-medium border px-100 py-050 text-body-small",
                        r.suggestedFix !== "prompt"
                          ? "border-border-brand bg-background-brand-subtlest text-text-brand hover:bg-background-brand-subtlest-pressed"
                          : "border-border text-text-subtle hover:bg-surface-sunken",
                      )}
                    >
                      <BookOpen className="h-3 w-3" /> Add to KB
                    </button>
                    <button
                      onClick={() => void onPromptFix(r)}
                      disabled={busyId === r.id}
                      className={cn(
                        "inline-flex items-center gap-050 rounded-medium border px-100 py-050 text-body-small disabled:opacity-50",
                        r.suggestedFix !== "kb"
                          ? "border-border-brand bg-background-brand-subtlest text-text-brand hover:bg-background-brand-subtlest-pressed"
                          : "border-border text-text-subtle hover:bg-surface-sunken",
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
                <td colSpan={6} className="px-150 py-300 text-center text-text-subtlest">
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
