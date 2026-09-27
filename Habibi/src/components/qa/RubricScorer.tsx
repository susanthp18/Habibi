import { Sparkles, Check, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Rubric, Scorecard, ScorecardEntry } from "@/api/types/qa";
import { sectionTotal } from "@/lib/qa";

export function RubricScorer({
  rubric,
  entries,
  onChange,
  readOnly,
}: {
  rubric: Rubric;
  entries: ScorecardEntry[];
  onChange: (next: ScorecardEntry[]) => void;
  readOnly?: boolean;
}) {
  const update = (criterionId: string, patch: Partial<ScorecardEntry>) => {
    const exists = entries.some((e) => e.criterionId === criterionId);
    if (exists) {
      onChange(entries.map((e) => (e.criterionId === criterionId ? { ...e, ...patch } : e)));
    } else {
      onChange([...entries, { criterionId, aiSuggested: 0, score: 0, ...patch }]);
    }
  };

  return (
    <div className="space-y-200">
      {rubric.sections.map((section) => {
        const subtotal = sectionTotal(section, entries);
        return (
          <div key={section.id} className="rounded-large border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-150 py-100">
              <div>
                <div className="text-body font-semibold text-text">{section.label}</div>
                <div className="text-body-small text-text-subtlest">Weight {section.weight}%</div>
              </div>
              <div className="text-right">
                <div className="text-body font-semibold text-text-brand">{subtotal.toFixed(0)}</div>
                <div className="text-body-small text-text-subtlest">Subtotal</div>
              </div>
            </div>
            <div className="divide-y divide-border">
              {section.criteria.map((c) => {
                const entry = entries.find((e) => e.criterionId === c.id) ?? {
                  criterionId: c.id,
                  aiSuggested: 0,
                  score: 0,
                };
                const diff = entry.score !== entry.aiSuggested;
                const liveLocked = Boolean(entry.note?.startsWith("[live]"));
                return (
                  <div key={c.id} className="px-150 py-150">
                    <div className="flex items-start justify-between gap-100">
                      <div className="min-w-0">
                        <div className="flex items-center gap-075 text-body-small font-medium text-text">
                          {c.label}
                          {c.critical && (
                            <span className="rounded bg-background-danger-subtler px-050 py-025 text-body-small font-semibold text-text-danger-bolder">
                              Critical
                            </span>
                          )}
                          {entry.tier ? (
                            <TierBadge entry={entry} />
                          ) : (
                            liveLocked && (
                              <span
                                className="inline-flex items-center gap-025 rounded bg-background-brand-subtlest px-050 py-025 text-body-small font-semibold text-text-brand"
                                title="Scored from live evidence — the model cannot overwrite this"
                              >
                                <Lock className="h-3 w-3" /> Live
                              </span>
                            )
                          )}
                        </div>
                        <div className="text-body-small text-text-subtle">{c.description}</div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="heading-small font-semibold text-text">
                          {entry.score.toFixed(0)}
                          <span className="text-body-small text-text-subtlest">/5</span>
                        </div>
                      </div>
                    </div>
                    <div className="mt-100 flex items-center gap-100">
                      <input
                        type="range"
                        min={0}
                        max={5}
                        step={1}
                        value={entry.score}
                        disabled={readOnly}
                        onChange={(e) =>
                          update(c.id, {
                            score: Number(e.target.value),
                            accepted: Number(e.target.value) === entry.aiSuggested,
                          })
                        }
                        className="h-050 flex-1 cursor-pointer accent-[var(--background-brand-bold)]"
                      />
                      <button
                        onClick={() => update(c.id, { score: entry.aiSuggested, accepted: true })}
                        disabled={readOnly}
                        className={cn(
                          "inline-flex items-center gap-050 rounded-full border px-075 py-025 text-body-small",
                          diff
                            ? "border-border-brand bg-background-brand-subtlest text-text-brand hover:bg-background-brand-subtlest-pressed"
                            : "border-border-success-subtle bg-background-success-subtler text-text-success-bolder",
                        )}
                        title="Accept AI suggestion"
                      >
                        {diff ? <Sparkles className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                        AI {entry.aiSuggested}
                      </button>
                    </div>
                    <input
                      type="text"
                      value={entry.note ?? ""}
                      onChange={(e) => update(c.id, { note: e.target.value })}
                      placeholder="Note…"
                      disabled={readOnly}
                      className="mt-075 w-full rounded border border-border bg-surface px-100 py-050 text-body-small outline-none focus:border-border-brand"
                    />
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const TIERS = {
  evidence: {
    label: "Evidence",
    hint: "Decided by rules on the call's own facts (flags, disclosures, tools)",
  },
  model: { label: "Signals", hint: "Decided by small models on the call (sentiment, intents)" },
  llm: { label: "Judge", hint: "Decided by the QA judge on the masked transcript" },
  human: { label: "Reviewer", hint: "Set by a person" },
} as const;

/** Who decided this criterion, and how sure it was; low confidence asks for a person. */
function TierBadge({ entry }: { entry: ScorecardEntry }) {
  const tier = TIERS[entry.tier ?? "model"];
  const confidence = entry.confidence ?? null;
  const unsure = entry.tier !== "human" && confidence != null && confidence < 0.5;
  const turns = (entry.evidence as { turns?: number[] } | null)?.turns;
  const title = [
    tier.hint,
    confidence != null ? `confidence ${Math.round(confidence * 100)}%` : null,
    turns?.length ? `turns ${turns.join(", ")}` : null,
    entry.modelVersion ? `by ${entry.modelVersion}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-025 rounded px-050 py-025 text-body-small font-semibold",
        unsure
          ? "bg-background-warning-subtler text-text-warning-bolder"
          : "bg-background-brand-subtlest text-text-brand",
      )}
    >
      {entry.tier === "evidence" && <Lock className="h-3 w-3" />}
      {unsure ? "Needs review" : tier.label}
      {!unsure && confidence != null && entry.tier !== "evidence" && entry.tier !== "human"
        ? ` ${Math.round(confidence * 100)}%`
        : ""}
    </span>
  );
}
