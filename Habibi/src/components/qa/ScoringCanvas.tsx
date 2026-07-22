import { useMemo, useState } from "react";
import { Send, Save, UserPlus, FileText } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { computeTotal, defaultRubric, findCall, type Scorecard, type ScorecardEntry } from "@/data/qa-seed";
import { formatDateTime, formatDuration } from "@/data/audit-seed";
import { ScoreBand } from "./ScoreBand";
import { RubricScorer } from "./RubricScorer";

export function ScoringCanvas({
  scorecard,
  onChangeEntries,
  onPublish,
  onSaveDraft,
  onAssignCoaching,
}: {
  scorecard: Scorecard | null;
  onChangeEntries: (id: string, entries: ScorecardEntry[]) => void;
  onPublish: (id: string) => void;
  onSaveDraft: (id: string) => void;
  onAssignCoaching: (scorecard: Scorecard) => void;
}) {
  const [tab, setTab] = useState<"rubric" | "transcript">("rubric");

  const call = useMemo(() => (scorecard ? findCall(scorecard.callId) : undefined), [scorecard]);
  const total = useMemo(() => (scorecard ? computeTotal(scorecard, defaultRubric) : 0), [scorecard]);

  if (!scorecard) {
    return (
      <div className="flex h-full items-center justify-center bg-surface-app text-[13px] text-text-muted">
        Select a call from the queue to begin scoring.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-app">
      <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold text-brand-navy">{scorecard.customerName}</div>
            <div className="text-[11px] text-text-secondary">
              {call ? `${formatDateTime(call.startedAt)} · ${formatDuration(call.duration)} · ${call.channel}` : "—"}
              {" · "}
              <span className="capitalize">{scorecard.handledBy.kind}</span> · {scorecard.handledBy.label} · {scorecard.disposition}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ScoreBand total={total} size="lg" />
            <span className="rounded-full border border-[var(--border-token)] px-2 py-0.5 text-[11px] capitalize text-text-secondary">
              {scorecard.status === "ai_draft" ? "AI draft" : scorecard.status}
            </span>
          </div>
        </div>
        <div className="mt-2 flex gap-1">
          {(["rubric", "transcript"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-md px-2.5 py-1 text-[12px] capitalize",
                tab === t ? "bg-brand-tint text-brand-primary-dark font-semibold" : "text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {t === "transcript" ? "Transcript" : "Rubric"}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {tab === "rubric" ? (
          <RubricScorer
            rubric={defaultRubric}
            entries={scorecard.entries}
            onChange={(next) => onChangeEntries(scorecard.id, next)}
          />
        ) : (
          <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
            <div className="flex items-center gap-2 border-b border-[var(--border-token)] px-3 py-2 text-[12px] text-text-secondary">
              <FileText className="h-3.5 w-3.5" /> Transcript
            </div>
            <div className="divide-y divide-[var(--border-token)]">
              {(call?.transcript ?? []).map((turn) => (
                <div key={turn.id} className="grid grid-cols-[80px_60px_1fr] gap-3 px-3 py-2 text-[12px]">
                  <span className="font-mono text-text-muted">{formatDuration(turn.t)}</span>
                  <span className={cn(
                    "capitalize",
                    turn.speaker === "customer" ? "text-brand-primary-dark font-medium" :
                    turn.speaker === "agent" || turn.speaker === "bot" ? "text-brand-navy font-medium" :
                    "text-text-muted italic",
                  )}>{turn.speaker}</span>
                  <span className="text-text-primary">{turn.text}</span>
                </div>
              ))}
              {(!call || call.transcript.length === 0) && (
                <div className="p-4 text-center text-[12px] text-text-muted">No transcript available.</div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-card px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => { onSaveDraft(scorecard.id); toast.success("Draft saved"); }}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-sunken"
          >
            <Save className="h-3.5 w-3.5" /> Save draft
          </button>
          <button
            onClick={() => onAssignCoaching(scorecard)}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-sunken"
          >
            <UserPlus className="h-3.5 w-3.5" /> Attach coaching
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[11px] text-text-muted">Total {total.toFixed(1)}/100</span>
            <button
              onClick={() => onPublish(scorecard.id)}
              className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-3 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark"
            >
              <Send className="h-3.5 w-3.5" /> Publish score
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
