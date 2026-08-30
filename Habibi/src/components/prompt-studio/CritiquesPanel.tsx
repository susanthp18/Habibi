// -----------------------------------------------------------------------------
// LLM-judge critiques — GET /eval/critiques, POST /eval/reports/{id}/critique.
//
// Both endpoints have been served since the eval harness shipped and nothing
// called either, so the judge's reading of a failed trial existed only as a
// database row.
//
// The one thing this panel must never imply is that a critique changed
// anything. It reads failed trials and proposes a line for SKILL.md; the
// backend asserts `writesProduction: false` twice — once on the row and once
// inside the diff — and the module it lives in says "Suggests a diff; never
// writes SKILL.md". A suggestion rendered like a changelog entry would have a
// QA lead believe the skill already says something it does not.
// -----------------------------------------------------------------------------

import { AlertCircle, MessageSquareQuote } from "lucide-react";

import { useSkillCritiques, type SkillCritique } from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";

function CritiqueRow({ critique }: { critique: SkillCritique }) {
  const diff = critique.suggestedDiff ?? {};
  return (
    <li className="border-b border-border px-150 py-100 last:border-b-0">
      <div className="flex flex-wrap items-center gap-075">
        <span className="font-mono text-body-small text-text">{diff.path ?? "SKILL.md"}</span>
        {critique.skillSlug && (
          <span className="text-body-small text-text-subtle">{critique.skillSlug}</span>
        )}
        <Lozenge tone="neutral">{critique.status}</Lozenge>
        {/* Asserted by the server on every row. Said out loud here because the
            whole value of the panel depends on nobody mistaking it. */}
        <Lozenge tone="information">Suggestion only</Lozenge>
        {critique.reportId && (
          <span className="ml-auto font-mono text-body-tiny text-text-subtlest">
            {critique.reportId}
          </span>
        )}
      </div>
      {diff.add && (
        <p className="mt-075 rounded-small border border-border bg-surface-sunken px-100 py-075 text-body-small text-text">
          “{diff.add}”
        </p>
      )}
      <div className="mt-050 flex flex-wrap gap-100 text-body-tiny text-text-subtlest">
        {diff.grader && <span>grader · {diff.grader}</span>}
        {diff.op && <span>{diff.op}</span>}
      </div>
    </li>
  );
}

export function CritiquesPanel() {
  const { data, isPending, isError, error } = useSkillCritiques();

  return (
    <section className="space-y-100">
      <div className="flex items-center gap-075">
        <MessageSquareQuote className="h-3.5 w-3.5 text-text-subtle" />
        <h3 className="text-body-small font-semibold text-text">Skill critiques</h3>
        <span className="ml-auto text-body-tiny text-text-subtlest">
          Never written to a skill — a human applies them
        </span>
      </div>

      {isPending ? (
        <LoadingState label="Loading critiques" />
      ) : isError ? (
        <div className="flex items-start gap-100 rounded-medium border border-border bg-surface px-150 py-100 text-body-small text-text-danger">
          <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
          <span>Could not load critiques. {(error as Error)?.message ?? ""}</span>
        </div>
      ) : (data ?? []).length === 0 ? (
        <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-150 text-center">
          <div className="text-body-small font-medium text-text">No critiques yet</div>
          <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">
            Critique a failed report above to have the judge read its trials and propose an
            objection line.
          </p>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-medium border border-border bg-surface">
          {(data ?? []).map((c) => (
            <CritiqueRow key={c.id} critique={c} />
          ))}
        </ul>
      )}
    </section>
  );
}
