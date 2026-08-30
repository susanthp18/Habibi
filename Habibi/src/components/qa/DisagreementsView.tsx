// -----------------------------------------------------------------------------
// Human-vs-AI disagreements — GET /eval/disagreements.
//
// The highest-value rubric-tuning input in the product, and nothing has ever
// rendered it. The query mines exactly two contradictions and ignores every
// near-miss: live QA said `pass` on a call humans banded `red`, or barged a
// call with `fail_critical` that humans banded `green`. Those are the two
// places the auto-scorer was demonstrably wrong in a direction that matters —
// one lets a bad call through, the other interrupts a good one.
//
// Read-only, and it has to look read-only. `applied` is false on the envelope
// and on every item, and the module is explicit: "Rubric tweaks only", "this
// never writes the rubric". A QA lead copies the tweak into the rubric builder
// by hand; nothing here changes scoring.
// -----------------------------------------------------------------------------

import { AlertCircle, ArrowRight } from "lucide-react";

import { useQaDisagreements, type QaDisagreement } from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const BAND_TONE: Record<string, LozengeTone> = {
  green: "success",
  amber: "warning",
  red: "danger",
};

const VERDICT_TONE: Record<string, LozengeTone> = {
  pass: "success",
  fail_critical: "danger",
};

function DisagreementRow({ item }: { item: QaDisagreement }) {
  return (
    <tr>
      <td className="px-150 py-100 font-mono text-text">{item.interactionId ?? "—"}</td>
      <td className="px-150 py-100">
        <Lozenge tone={VERDICT_TONE[item.liveVerdict] ?? "neutral"}>{item.liveVerdict}</Lozenge>
      </td>
      <td className="px-150 py-100">
        <div className="flex items-center gap-075">
          <ArrowRight className="h-3.5 w-3.5 text-text-subtlest" />
          <Lozenge tone={BAND_TONE[item.humanBand] ?? "neutral"}>{item.humanBand}</Lozenge>
        </div>
      </td>
      <td className="px-150 py-100 text-right font-mono tabular-nums text-text-subtle">
        {/* Null means the scorecard carried no total, which is not a score of 0. */}
        {item.humanScore === null ? "—" : item.humanScore.toFixed(0)}
      </td>
      <td className="px-150 py-100 text-text-subtle">{item.suggestedRubricTweak}</td>
    </tr>
  );
}

export function DisagreementsView() {
  const { data, isPending, isError, error } = useQaDisagreements();

  if (isPending) {
    return <LoadingState label="Loading disagreements" />;
  }

  if (isError) {
    return (
      <div className="flex items-start gap-100 rounded-medium border border-border bg-surface px-150 py-100 text-body-small text-text-danger">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <span>
          Disagreement mining unavailable — cannot confirm whether the auto-scorer and the humans
          agree. {(error as Error)?.message ?? ""}
        </span>
      </div>
    );
  }

  const items = data?.items ?? [];

  return (
    <div className="space-y-150">
      <div>
        <div className="flex flex-wrap items-center gap-100">
          <h2 className="text-body font-semibold text-text">Human vs AI disagreements</h2>
          <Lozenge tone="information">Read-only — never writes the rubric</Lozenge>
        </div>
        <p className="mt-050 max-w-prose text-body-small text-text-subtle">
          Calls where live QA and a final human scorecard reached opposite conclusions: passed but
          banded red, or barged but banded green. Everything else agrees closely enough not to be
          worth a rubric change. Copy a tweak into the rubric builder yourself — nothing on this tab
          applies one.
        </p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-250 text-center">
          <div className="text-body font-medium text-text">No disagreements</div>
          <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">
            No finalised scorecard contradicts its live-QA verdict. This is a real result, not an
            empty screen — it means the auto-scorer and the humans have not diverged on any call
            scored so far.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-medium border border-border bg-surface">
          <table className="w-full text-body-small">
            <thead>
              <tr className="border-b border-border text-text-subtlest">
                <th className="px-150 py-100 text-left font-semibold">Interaction</th>
                <th className="px-150 py-100 text-left font-semibold">Live QA said</th>
                <th className="px-150 py-100 text-left font-semibold">Humans said</th>
                <th className="px-150 py-100 text-right font-semibold">Human score</th>
                <th className="px-150 py-100 text-left font-semibold">Suggested rubric tweak</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item, i) => (
                <DisagreementRow key={`${item.interactionId}-${i}`} item={item} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
