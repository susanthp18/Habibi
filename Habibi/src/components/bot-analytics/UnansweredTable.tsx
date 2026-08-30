import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { BookOpen, Bot, CheckCircle2, AlertTriangle, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { INTENTS, type UnansweredQuestion } from "@/data/bot-analytics-seed";
import { linkKbGap, promoteGapToSkill } from "@/api/kb";
import { usePublishedPromptVersion } from "@/api/prompt-studio";
import { USE_MOCK } from "@/api/config";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

export function UnansweredTable({ questions }: { questions: UnansweredQuestion[] }) {
  const navigate = useNavigate();
  const publishedQuery = usePublishedPromptVersion();
  const [busyId, setBusyId] = useState<string | null>(null);

  const uncovered = questions.filter((r) => !r.hasKbDoc).length;

  const intentLabel = (id: string) => INTENTS.find((i) => i.id === id)?.label ?? id;

  const onPromoteSkill = async (r: UnansweredQuestion) => {
    setBusyId(r.id);
    try {
      if (!USE_MOCK) {
        const created = await promoteGapToSkill(r.id);
        toast.success("Draft skill created — unsigned until you sign it");
        void navigate({ to: "/agent-studio/skills/$skillId", params: { skillId: created.id } });
        return;
      }
      void navigate({ to: "/agent-studio/skills" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not promote gap");
    } finally {
      setBusyId(null);
    }
  };

  const onAddToKb = (r: UnansweredQuestion) => {
    void navigate({
      to: "/knowledge-base",
      search: { gapId: r.id, q: r.text, tab: "gaps" },
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
            toast.message("Gap link skipped", {
              description: err instanceof Error ? err.message : "Could not persist prompt link",
            });
          }
        }
      }
      void navigate({
        to: "/agent-studio/$botId",
        params: { botId: "kaia-v2-4" },
        search: { unansweredId: r.id, note: r.text },
      });
    } finally {
      setBusyId(null);
    }
  };

  const columns = useMemo<RecordsColumn<UnansweredQuestion>[]>(
    () => [
      {
        id: "question",
        header: "Question",
        sticky: true,
        sortable: true,
        sortValue: (r) => r.text,
        className: "min-w-[16rem]",
        cell: (r) => (
          <span className="line-clamp-2 text-body text-text" title={r.text}>
            {r.text}
          </span>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">questions</span>
          </span>
        ),
      },
      {
        id: "hits",
        header: "Hits",
        sortable: true,
        sortValue: (r) => r.hits,
        align: "right",
        className: "min-w-[4.5rem] whitespace-nowrap",
        cell: (r) => <span className="font-semibold tabular-nums text-text">{r.hits}</span>,
        footer: (visible) => (
          <span className="tabular-nums">{visible.reduce((s, r) => s + r.hits, 0)}</span>
        ),
      },
      {
        id: "intent",
        header: "Top intent",
        sortable: true,
        sortValue: (r) => intentLabel(r.topIntent),
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) => <RecordsTag name={intentLabel(r.topIntent)} />,
      },
      {
        id: "coverage",
        header: "KB coverage",
        sortable: true,
        sortValue: (r) => (r.hasKbDoc ? 1 : 0),
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) =>
          r.hasKbDoc ? (
            <Lozenge tone="success">
              <CheckCircle2 className="h-3 w-3" /> Doc exists
            </Lozenge>
          ) : (
            <Lozenge tone="warning">
              <AlertTriangle className="h-3 w-3" /> Missing
            </Lozenge>
          ),
      },
      {
        id: "lastSeen",
        header: "Last seen",
        sortable: true,
        sortValue: (r) => Date.parse(r.lastSeen) || 0,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) => <span className="text-body-small text-text-subtle">{r.lastSeen}</span>,
      },
      {
        id: "actions",
        header: "Actions",
        align: "right",
        className: "min-w-[22rem] whitespace-nowrap",
        cell: (r) => (
          <div className="flex justify-end gap-050">
            <button
              type="button"
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
              type="button"
              onClick={() => void onPromoteSkill(r)}
              disabled={busyId === r.id}
              className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-050 text-body-small text-text-subtle hover:bg-surface-sunken disabled:opacity-50"
            >
              <Layers className="h-3 w-3" /> Promote to skill
            </button>
            <button
              type="button"
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
        ),
      },
    ],
    [busyId],
  );

  return (
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      <div className="border-b border-border px-150 py-100">
        <div className="flex items-center justify-between gap-150">
          <div>
            <div className="text-body font-semibold text-text">
              Top unanswered / RAG-miss questions
            </div>
            <div className="text-body-small text-text-subtlest">
              Each row is a candidate for Knowledge Base or Prompt Studio work
            </div>
          </div>
          <Lozenge tone="warning">{uncovered} without KB coverage</Lozenge>
        </div>
      </div>
      <RecordsTable
        rows={questions}
        getRowId={(r) => r.id}
        columns={columns}
        defaultSort={{ id: "hits", dir: -1 }}
        ariaLabel="Unanswered questions"
        tableClassName="min-w-[56rem]"
        className="rounded-none border-0"
        emptyMessage="No unanswered questions recorded."
      />
    </div>
  );
}
