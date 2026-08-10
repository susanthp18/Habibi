import { useState } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Rubric, RubricCriterion, RubricSection } from "@/data/qa-seed";

export function RubricBuilderSheet({
  open,
  onClose,
  rubric,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  rubric: Rubric;
  onSave: (r: Rubric) => void;
}) {
  const [draft, setDraft] = useState<Rubric>(rubric);
  if (!open) return null;

  const totalWeight = draft.sections.reduce((a, s) => a + s.weight, 0);
  const validSum = totalWeight === 100;

  const updateSection = (id: string, patch: Partial<RubricSection>) => {
    setDraft({ ...draft, sections: draft.sections.map((s) => (s.id === id ? { ...s, ...patch } : s)) });
  };
  const addCriterion = (sectionId: string) => {
    const c: RubricCriterion = { id: `c-${Date.now()}`, label: "New criterion", description: "", weight: 10 };
    updateSection(sectionId, { criteria: [...(draft.sections.find((s) => s.id === sectionId)?.criteria ?? []), c] });
  };
  const updateCriterion = (sectionId: string, cid: string, patch: Partial<RubricCriterion>) => {
    const section = draft.sections.find((s) => s.id === sectionId);
    if (!section) return;
    updateSection(sectionId, { criteria: section.criteria.map((c) => (c.id === cid ? { ...c, ...patch } : c)) });
  };
  const removeCriterion = (sectionId: string, cid: string) => {
    const section = draft.sections.find((s) => s.id === sectionId);
    if (!section) return;
    updateSection(sectionId, { criteria: section.criteria.filter((c) => c.id !== cid) });
  };
  const addSection = () => {
    setDraft({
      ...draft,
      sections: [...draft.sections, { id: `s-${Date.now()}`, label: "New section", weight: 0, criteria: [] }],
    });
  };
  const removeSection = (id: string) => setDraft({ ...draft, sections: draft.sections.filter((s) => s.id !== id) });

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col bg-surface shadow-overlay" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-200 py-150">
          <div>
            <div className="text-[0.875rem] font-semibold text-text">Edit rubric — {draft.name}</div>
            <div className="text-body-small text-text-subtlest">Version {draft.version} · applies to all future scorecards.</div>
          </div>
          <button onClick={onClose} className="rounded p-050 hover:bg-surface-sunken"><X className="h-4 w-4" /></button>
        </div>

        <div className="border-b border-border bg-surface px-200 py-100">
          <div className="mb-050 flex items-center justify-between text-body-small text-text-subtle">
            <span>Section weights sum</span>
            <span className={cn("font-semibold", validSum ? "text-text-success-bolder" : "text-text-danger-bolder")}>{totalWeight} / 100</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
            <div className={cn("h-full", validSum ? "bg-background-success-bold" : "bg-background-danger-bold")} style={{ width: `${Math.min(100, totalWeight)}%` }} />
          </div>
        </div>

        <div className="flex-1 space-y-150 overflow-y-auto p-200">
          {draft.sections.map((section) => (
            <div key={section.id} className="rounded-large border border-border">
              <div className="flex items-center gap-100 border-b border-border bg-surface-sunken px-150 py-100">
                <input
                  value={section.label}
                  onChange={(e) => updateSection(section.id, { label: e.target.value })}
                  className="flex-1 rounded border border-border bg-surface px-100 py-050 text-body-small font-semibold text-text"
                />
                <label className="flex items-center gap-050 text-body-small text-text-subtle">
                  Weight
                  <input
                    type="number"
                    value={section.weight}
                    onChange={(e) => updateSection(section.id, { weight: Number(e.target.value) })}
                    className="w-14 rounded border border-border bg-surface px-050 py-025 text-right"
                  />%
                </label>
                <button onClick={() => removeSection(section.id)} className="rounded p-050 text-text-danger hover:bg-background-danger-subtler">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="divide-y divide-border">
                {section.criteria.map((c) => (
                  <div key={c.id} className="grid grid-cols-[1fr_60px_28px] gap-100 px-150 py-100 text-body-small">
                    <div>
                      <input
                        value={c.label}
                        onChange={(e) => updateCriterion(section.id, c.id, { label: e.target.value })}
                        className="w-full rounded border border-border bg-surface px-100 py-050 font-medium"
                      />
                      <input
                        value={c.description}
                        onChange={(e) => updateCriterion(section.id, c.id, { description: e.target.value })}
                        placeholder="Description…"
                        className="mt-050 w-full rounded border border-border bg-surface px-100 py-050 text-body-small"
                      />
                      <label className="mt-050 inline-flex items-center gap-050 text-body-small text-text-subtle">
                        <input
                          type="checkbox"
                          checked={!!c.critical}
                          onChange={(e) => updateCriterion(section.id, c.id, { critical: e.target.checked })}
                        />
                        Critical (zero triggers auto-fail cap)
                      </label>
                    </div>
                    <input
                      type="number"
                      value={c.weight}
                      onChange={(e) => updateCriterion(section.id, c.id, { weight: Number(e.target.value) })}
                      className="h-fit rounded border border-border bg-surface px-050 py-050 text-right"
                    />
                    <button onClick={() => removeCriterion(section.id, c.id)} className="h-fit rounded p-050 text-text-danger hover:bg-background-danger-subtler">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                <button onClick={() => addCriterion(section.id)} className="flex w-full items-center gap-050 px-150 py-100 text-body-small text-text-brand hover:bg-background-brand-subtlest">
                  <Plus className="h-3 w-3" /> Add criterion
                </button>
              </div>
            </div>
          ))}
          <button onClick={addSection} className="flex w-full items-center justify-center gap-050 rounded-large border border-dashed border-border py-100 text-body-small text-text-brand hover:bg-background-brand-subtlest">
            <Plus className="h-3.5 w-3.5" /> Add section
          </button>
        </div>

        <div className="flex items-center justify-end gap-100 border-t border-border px-200 py-150">
          <button onClick={onClose} className="rounded-medium border border-border px-150 py-075 text-body-small hover:bg-surface-sunken">Cancel</button>
          <button
            disabled={!validSum}
            onClick={() => { onSave(draft); toast.success("Rubric saved", { description: `${draft.name} · ${draft.version}` }); onClose(); }}
            className="rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed disabled:opacity-40"
          >
            Save rubric
          </button>
        </div>
      </div>
    </div>
  );
}
