import { Sparkles, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { sectionTotal, type Rubric, type Scorecard, type ScorecardEntry } from "@/data/qa-seed";

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
    <div className="space-y-4">
      {rubric.sections.map((section) => {
        const subtotal = sectionTotal(section, entries);
        return (
          <div key={section.id} className="rounded-lg border border-[var(--border-token)] bg-surface-card">
            <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
              <div>
                <div className="text-[13px] font-semibold text-brand-navy">{section.label}</div>
                <div className="text-[11px] text-text-muted">Weight {section.weight}%</div>
              </div>
              <div className="text-right">
                <div className="text-[15px] font-semibold text-brand-primary-dark">{subtotal.toFixed(0)}</div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted">Subtotal</div>
              </div>
            </div>
            <div className="divide-y divide-[var(--border-token)]">
              {section.criteria.map((c) => {
                const entry = entries.find((e) => e.criterionId === c.id) ?? { criterionId: c.id, aiSuggested: 0, score: 0 };
                const diff = entry.score !== entry.aiSuggested;
                return (
                  <div key={c.id} className="px-3 py-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-text-primary">
                          {c.label}
                          {c.critical && (
                            <span className="rounded bg-red-50 px-1 py-0.5 text-[9px] font-semibold uppercase text-red-700">Critical</span>
                          )}
                        </div>
                        <div className="text-[11px] text-text-secondary">{c.description}</div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="text-[16px] font-semibold text-brand-navy">{entry.score.toFixed(0)}<span className="text-[11px] text-text-muted">/5</span></div>
                      </div>
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <input
                        type="range"
                        min={0}
                        max={5}
                        step={1}
                        value={entry.score}
                        disabled={readOnly}
                        onChange={(e) => update(c.id, { score: Number(e.target.value), accepted: Number(e.target.value) === entry.aiSuggested })}
                        className="h-1 flex-1 cursor-pointer accent-[var(--brand-primary)]"
                      />
                      <button
                        onClick={() => update(c.id, { score: entry.aiSuggested, accepted: true })}
                        disabled={readOnly}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]",
                          diff
                            ? "border-brand-primary bg-brand-tint text-brand-primary-dark hover:bg-brand-tint-strong"
                            : "border-emerald-200 bg-emerald-50 text-emerald-700",
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
                      className="mt-1.5 w-full rounded border border-[var(--border-token)] bg-surface-app px-2 py-1 text-[11px] outline-none focus:border-brand-primary"
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
