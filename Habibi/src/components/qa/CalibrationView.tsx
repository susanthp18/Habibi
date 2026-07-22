import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { computeTotal, defaultRubric, type CalibrationSession } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";

export function CalibrationView({ sessions, onClose }: { sessions: CalibrationSession[]; onClose: (id: string) => void }) {
  const [activeId, setActiveId] = useState<string>(sessions[0]?.id ?? "");
  const active = sessions.find((s) => s.id === activeId) ?? sessions[0];

  if (!active) {
    return <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-6 text-center text-[12px] text-text-muted">No calibration sessions.</div>;
  }

  const targetTotal = computeTotal({ entries: active.target } as any, defaultRubric);

  return (
    <div className="grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)]">
      <div className="space-y-1 rounded-lg border border-[var(--border-token)] bg-surface-card p-2">
        <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Sessions</div>
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveId(s.id)}
            className={cn(
              "w-full rounded-md px-2 py-2 text-left text-[12px]",
              s.id === active.id ? "bg-brand-tint text-brand-primary-dark" : "hover:bg-surface-sunken text-text-primary",
            )}
          >
            <div className="font-medium">{s.name}</div>
            <div className="text-[11px] text-text-muted">{s.customerName} · {s.reviewers.length} reviewers · {s.status}</div>
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
        <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
          <div>
            <div className="text-[13px] font-semibold text-brand-navy">{active.name}</div>
            <div className="text-[11px] text-text-muted">Target score for {active.customerName}: <ScoreBand total={targetTotal} size="sm" /></div>
          </div>
          {active.status === "active" && (
            <button
              onClick={() => { onClose(active.id); toast.success("Calibration closed", { description: active.name }); }}
              className="rounded-md bg-brand-primary px-2.5 py-1 text-[11px] font-medium text-white hover:bg-brand-primary-dark"
            >
              Close variance
            </button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-muted">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Reviewer</th>
                {defaultRubric.sections.map((s) => (
                  <th key={s.id} className="px-3 py-2 text-left font-medium">{s.label}</th>
                ))}
                <th className="px-3 py-2 text-right font-medium">Total</th>
                <th className="px-3 py-2 text-right font-medium">Δ vs target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-token)]">
              <tr className="bg-brand-tint/40">
                <td className="px-3 py-2 font-semibold text-brand-navy">Target</td>
                {defaultRubric.sections.map((s) => {
                  const sub = computeTotal({ entries: active.target.filter((e) => s.criteria.some((c) => c.id === e.criterionId)) } as any, { ...defaultRubric, sections: [s] });
                  return <td key={s.id} className="px-3 py-2 text-text-primary">{sub.toFixed(0)}</td>;
                })}
                <td className="px-3 py-2 text-right"><ScoreBand total={targetTotal} size="sm" /></td>
                <td className="px-3 py-2 text-right text-text-muted">—</td>
              </tr>
              {active.reviewers.map((r) => {
                const total = computeTotal({ entries: r.entries } as any, defaultRubric);
                const delta = total - targetTotal;
                const bad = Math.abs(delta) > 8;
                return (
                  <tr key={r.reviewer}>
                    <td className="px-3 py-2 font-medium text-brand-navy">{r.reviewer}</td>
                    {defaultRubric.sections.map((s) => {
                      const sub = computeTotal({ entries: r.entries.filter((e) => s.criteria.some((c) => c.id === e.criterionId)) } as any, { ...defaultRubric, sections: [s] });
                      return <td key={s.id} className="px-3 py-2 text-text-primary">{sub.toFixed(0)}</td>;
                    })}
                    <td className="px-3 py-2 text-right"><ScoreBand total={total} size="sm" /></td>
                    <td className={cn(
                      "px-3 py-2 text-right font-medium",
                      bad ? "text-red-700" : "text-emerald-700",
                    )}>
                      {delta > 0 ? "+" : ""}{delta.toFixed(1)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
