import { useMemo } from "react";
import { useNavigate } from "@tanstack/react-router";
import { BookOpen, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { UnansweredQuestion } from "@/api/types/bot-analytics";
import { INTENTS } from "@/lib/bot-analytics";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

export function UnansweredTable({
  questions,
  isLoading = false,
  isError = false,
  error,
}: {
  questions: UnansweredQuestion[];
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
}) {
  const navigate = useNavigate();

  const uncovered = questions.filter((r) => !r.hasKbDoc).length;

  const intentLabel = (id: string) => INTENTS.find((i) => i.id === id)?.label ?? id;

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
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (r) => (
          <div className="flex justify-end gap-050">
            <button
              type="button"
              onClick={() => void navigate({ to: "/studio/files" })}
              className={cn(
                "inline-flex items-center gap-050 rounded-medium border px-100 py-050 text-body-small",
                r.suggestedFix !== "prompt"
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand hover:bg-background-brand-subtlest-pressed"
                  : "border-border text-text-subtle hover:bg-surface-sunken",
              )}
            >
              <BookOpen className="h-3 w-3" /> Add to KB
            </button>
          </div>
        ),
      },
    ],
    [navigate],
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
              Each row is a candidate for Voice Studio knowledge base work
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
        isLoading={isLoading}
        isError={isError}
        error={error}
        errorLabel="unanswered questions"
        ariaLabel="Unanswered questions"
        tableClassName="min-w-[56rem]"
        className="rounded-none border-0"
        emptyMessage="No unanswered questions recorded."
      />
    </div>
  );
}
