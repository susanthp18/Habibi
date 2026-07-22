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
      <div className="flex h-full w-full max-w-2xl flex-col bg-surface-card shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border-token)] px-4 py-3">
          <div>
            <div className="text-[15px] font-semibold text-brand-navy">Edit rubric — {draft.name}</div>
            <div className="text-[11px] text-text-muted">Version {draft.version} · applies to all future scorecards.</div>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-surface-sunken"><X className="h-4 w-4" /></button>
        </div>

        <div className="border-b border-[var(--border-token)] bg-surface-app px-4 py-2">
          <div className="mb-1 flex items-center justify-between text-[11px] text-text-secondary">
            <span>Section weights sum</span>
            <span className={cn("font-semibold", validSum ? "text-emerald-700" : "text-red-700")}>{totalWeight} / 100</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
            <div className={cn("h-full", validSum ? "bg-emerald-500" : "bg-red-500")} style={{ width: `${Math.min(100, totalWeight)}%` }} />
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {draft.sections.map((section) => (
            <div key={section.id} className="rounded-lg border border-[var(--border-token)]">
              <div className="flex items-center gap-2 border-b border-[var(--border-token)] bg-surface-sunken px-3 py-2">
                <input
                  value={section.label}
                  onChange={(e) => updateSection(section.id, { label: e.target.value })}
                  className="flex-1 rounded border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[12px] font-semibold text-brand-navy"
                />
                <label className="flex items-center gap-1 text-[11px] text-text-secondary">
                  Weight
                  <input
                    type="number"
                    value={section.weight}
                    onChange={(e) => updateSection(section.id, { weight: Number(e.target.value) })}
                    className="w-14 rounded border border-[var(--border-token)] bg-surface-card px-1 py-0.5 text-right"
                  />%
                </label>
                <button onClick={() => removeSection(section.id)} className="rounded p-1 text-red-600 hover:bg-red-50">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="divide-y divide-[var(--border-token)]">
                {section.criteria.map((c) => (
                  <div key={c.id} className="grid grid-cols-[1fr_60px_28px] gap-2 px-3 py-2 text-[12px]">
                    <div>
                      <input
                        value={c.label}
                        onChange={(e) => updateCriterion(section.id, c.id, { label: e.target.value })}
                        className="w-full rounded border border-[var(--border-token)] bg-surface-app px-2 py-1 font-medium"
                      />
                      <input
                        value={c.description}
                        onChange={(e) => updateCriterion(section.id, c.id, { description: e.target.value })}
                        placeholder="Description…"
                        className="mt-1 w-full rounded border border-[var(--border-token)] bg-surface-app px-2 py-1 text-[11px]"
                      />
                      <label className="mt-1 inline-flex items-center gap-1 text-[11px] text-text-secondary">
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
                      className="h-fit rounded border border-[var(--border-token)] bg-surface-app px-1 py-1 text-right"
                    />
                    <button onClick={() => removeCriterion(section.id, c.id)} className="h-fit rounded p-1 text-red-600 hover:bg-red-50">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                <button onClick={() => addCriterion(section.id)} className="flex w-full items-center gap-1 px-3 py-2 text-[11px] text-brand-primary hover:bg-brand-tint">
                  <Plus className="h-3 w-3" /> Add criterion
                </button>
              </div>
            </div>
          ))}
          <button onClick={addSection} className="flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-[var(--border-token)] py-2 text-[12px] text-brand-primary hover:bg-brand-tint">
            <Plus className="h-3.5 w-3.5" /> Add section
          </button>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-token)] px-4 py-3">
          <button onClick={onClose} className="rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] hover:bg-surface-sunken">Cancel</button>
          <button
            disabled={!validSum}
            onClick={() => { onSave(draft); toast.success("Rubric saved", { description: `${draft.name} · ${draft.version}` }); onClose(); }}
            className="rounded-md bg-brand-primary px-3 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark disabled:opacity-40"
          >
            Save rubric
          </button>
        </div>
      </div>
    </div>
  );
}
