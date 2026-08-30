import { useMemo, useState } from "react";
import { Send, Save, UserPlus, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCalls } from "@/api/audit";
import {
  allCriteria,
  computeTotal,
  type Rubric,
  type Scorecard,
  type ScorecardEntry,
} from "@/data/qa-seed";
import { formatDateTime, formatDuration } from "@/data/audit-seed";
import { ScoreBand } from "./ScoreBand";
import { RubricScorer } from "./RubricScorer";
import { Lozenge } from "@/components/ui/lozenge";

export function ScoringCanvas({
  scorecard,
  rubric,
  onChangeEntries,
  onPublish,
  onSaveDraft,
  onAssignCoaching,
}: {
  scorecard: Scorecard | null;
  rubric: Rubric;
  onChangeEntries: (id: string, entries: ScorecardEntry[]) => void;
  onPublish: (id: string) => void;
  onSaveDraft: (id: string) => void;
  onAssignCoaching: (scorecard: Scorecard) => void;
}) {
  const [tab, setTab] = useState<"rubric" | "transcript">("rubric");
  const { data: calls } = useCalls();

  const call = useMemo(
    () => (scorecard ? calls?.find((c) => c.id === scorecard.callId) : undefined),
    [scorecard, calls],
  );
  const total = useMemo(
    () => (scorecard ? computeTotal(scorecard, rubric) : 0),
    [scorecard, rubric],
  );
  // Publish is gated on every rubric criterion having an entry (score 0 counts).
  const { scoredCount, totalCriteria } = useMemo(() => {
    const criteria = allCriteria(rubric);
    const scored = scorecard
      ? criteria.filter((c) => scorecard.entries.some((e) => e.criterionId === c.id)).length
      : 0;
    return { scoredCount: scored, totalCriteria: criteria.length };
  }, [scorecard, rubric]);
  const allScored = totalCriteria > 0 && scoredCount === totalCriteria;

  if (!scorecard) {
    return (
      <div className="flex h-full items-center justify-center bg-surface text-body text-text-subtlest">
        Select a call from the queue to begin scoring.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="shrink-0 border-b border-border bg-surface px-200 py-150">
        <div className="flex flex-wrap items-center gap-100">
          <div className="min-w-0">
            <div className="truncate text-body font-semibold text-text">
              {scorecard.customerName}
            </div>
            <div className="text-body-small text-text-subtle">
              {call
                ? `${formatDateTime(call.startedAt)} · ${formatDuration(call.duration)} · ${call.channel}`
                : "—"}
              {" · "}
              <span className="capitalize">{scorecard.handledBy.kind}</span> ·{" "}
              {scorecard.handledBy.label} · {scorecard.disposition}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-100">
            <ScoreBand total={total} size="lg" />
            <Lozenge tone="neutral" className="border-border capitalize">
              {scorecard.status === "ai_draft" ? "AI draft" : scorecard.status}
            </Lozenge>
          </div>
        </div>
        <div className="mt-100 flex gap-050">
          {(["rubric", "transcript"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-medium px-150 py-050 text-body-small capitalize",
                tab === t
                  ? "bg-background-brand-subtlest text-text-brand font-semibold"
                  : "text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {t === "transcript" ? "Transcript" : "Rubric"}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-200 py-200">
        {tab === "rubric" ? (
          <RubricScorer
            rubric={rubric}
            entries={scorecard.entries}
            onChange={(next) => onChangeEntries(scorecard.id, next)}
          />
        ) : (
          <div className="rounded-large border border-border bg-surface">
            <div className="flex items-center gap-100 border-b border-border px-150 py-100 text-body-small text-text-subtle">
              <FileText className="h-3.5 w-3.5" /> Transcript
            </div>
            <div className="divide-y divide-border">
              {(call?.transcript ?? []).map((turn) => (
                <div
                  key={turn.id}
                  className="grid grid-cols-[80px_60px_1fr] gap-150 px-150 py-100 text-body-small"
                >
                  <span className="font-mono text-text-subtlest">{formatDuration(turn.t)}</span>
                  <span
                    className={cn(
                      "capitalize",
                      turn.speaker === "customer"
                        ? "text-text-brand font-medium"
                        : turn.speaker === "agent" || turn.speaker === "bot"
                          ? "text-text font-medium"
                          : "text-text-subtlest italic",
                    )}
                  >
                    {turn.speaker}
                  </span>
                  <span className="text-text">{turn.text}</span>
                </div>
              ))}
              {(!call || call.transcript.length === 0) && (
                <div className="p-200 text-center text-body-small text-text-subtlest">
                  No transcript available.
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-200 py-150">
        <div className="flex flex-wrap items-center gap-100">
          <button
            onClick={() => onSaveDraft(scorecard.id)}
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
          >
            <Save className="h-3.5 w-3.5" /> Save draft
          </button>
          <button
            onClick={() => onAssignCoaching(scorecard)}
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
          >
            <UserPlus className="h-3.5 w-3.5" /> Attach coaching
          </button>
          <div className="ml-auto flex items-center gap-100">
            <span className="text-body-small text-text-subtlest">
              {allScored
                ? `Total ${total.toFixed(1)}/100`
                : `${scoredCount}/${totalCriteria} criteria scored`}
            </span>
            <button
              onClick={() => onPublish(scorecard.id)}
              disabled={!allScored}
              title={allScored ? undefined : "Score every criterion before publishing"}
              className={cn(
                "inline-flex items-center gap-050 rounded-medium px-150 py-075 text-body-small font-medium text-white",
                allScored
                  ? "bg-background-brand-bold hover:bg-background-brand-bold-pressed"
                  : "cursor-not-allowed bg-background-brand-bold/40",
              )}
            >
              <Send className="h-3.5 w-3.5" /> Publish score
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
