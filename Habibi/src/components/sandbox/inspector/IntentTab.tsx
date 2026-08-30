import { INTENT_LABEL, type SandboxTurn, type IntentKey } from "@/data/sandbox-seed";
import type { TurnAnalysisEvent } from "../voice/liveEvents";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

/**
 * Classifier output for the most recent customer turn.
 *
 * Two sources, deliberately. A text rehearsal classifies in the browser and the
 * scores live on the turn. A live call classifies server-side — keyword first,
 * then an LLM refinement — and streams the result over RTVI, because the voice
 * transcript the browser receives carries text only. Before this tab read the
 * live stream it showed "Send a customer message to classify intent" for the
 * whole of a five-minute call.
 */
export function IntentTab({
  turns,
  analysis = [],
}: {
  turns: SandboxTurn[];
  analysis?: TurnAnalysisEvent[];
}) {
  const live = [...analysis]
    .reverse()
    .find((t) => t.speaker === "customer" && t.intentScores && Object.keys(t.intentScores).length);
  if (live?.intentScores) {
    return (
      <Scores
        scores={live.intentScores}
        top={live.intent}
        source={live.source}
        label={(k) => INTENT_LABEL[k as IntentKey] ?? k}
      />
    );
  }

  const lastCustomer = [...turns].reverse().find((t) => t.role === "customer" && t.intentScores);
  if (!lastCustomer?.intentScores) {
    return (
      <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
        Send a customer message to classify intent.
      </div>
    );
  }
  return (
    <Scores
      scores={lastCustomer.intentScores as Record<string, number>}
      label={(k) => INTENT_LABEL[k as IntentKey] ?? k}
    />
  );
}

function Scores({
  scores,
  top,
  source,
  label,
}: {
  scores: Record<string, number>;
  top?: string;
  source?: "keyword" | "llm";
  label: (k: string) => string;
}) {
  const entries = Object.entries(scores)
    .filter(([, v]) => Number.isFinite(v))
    .sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
        No intent scores for this turn.
      </div>
    );
  }
  const winner = top ?? entries[0][0];
  return (
    <div className="space-y-100">
      <div className="flex items-center justify-between gap-100">
        <span className="text-body-small text-text-subtlest">
          Classifier output for last customer turn
        </span>
        {source ? (
          // "keyword" is the provisional reading the pipeline persists
          // immediately; "llm" replaces it a turn or two later. Showing which
          // one is on screen stops a stale baseline from reading as settled.
          <Lozenge tone={source === "llm" ? "success" : "neutral"}>
            {source === "llm" ? "LLM" : "keyword"}
          </Lozenge>
        ) : null}
      </div>
      {entries.map(([k, v]) => (
        <div key={k}>
          <div className="mb-025 flex items-center justify-between text-body-small">
            <span
              className={cn(k === winner ? "font-semibold text-text-brand" : "text-text-subtle")}
            >
              {label(k)}
            </span>
            <span className="font-mono text-body-small text-text-subtlest">
              {(v * 100).toFixed(0)}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-surface-sunken">
            <div
              className={cn(
                "h-full",
                k === winner ? "bg-background-brand-bold" : "bg-background-brand-bold/40",
              )}
              style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
