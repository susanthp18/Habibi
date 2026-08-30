import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { computeTotal, defaultRubric, type CalibrationSession } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";

export function CalibrationView({
  sessions,
  onClose,
}: {
  sessions: CalibrationSession[];
  onClose: (id: string) => void;
}) {
  const [activeId, setActiveId] = useState<string>(sessions[0]?.id ?? "");
  const active = sessions.find((s) => s.id === activeId) ?? sessions[0];

  if (!active) {
    return (
      <div className="rounded-large border border-border bg-surface p-300 text-center text-body-small text-text-subtlest">
        No calibration sessions.
      </div>
    );
  }

  const targetTotal = computeTotal({ entries: active.target }, defaultRubric);

  return (
    <div className="grid gap-150 lg:grid-cols-[240px_minmax(0,1fr)]">
      <div className="space-y-050 rounded-large border border-border bg-surface p-100">
        <div className="px-100 pb-050 text-body-small font-semibold text-text-subtlest">
          Sessions
        </div>
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveId(s.id)}
            className={cn(
              "w-full rounded-medium px-100 py-100 text-left text-body-small",
              s.id === active.id
                ? "bg-background-brand-subtlest text-text-brand"
                : "hover:bg-surface-sunken text-text",
            )}
          >
            <div className="font-medium">{s.name}</div>
            <div className="text-body-small text-text-subtlest">
              {s.customerName} · {s.reviewers.length} reviewers · {s.status}
            </div>
          </button>
        ))}
      </div>

      <div className="rounded-large border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-150 py-100">
          <div>
            <div className="text-body font-semibold text-text">{active.name}</div>
            <div className="text-body-small text-text-subtlest">
              Target score for {active.customerName}: <ScoreBand total={targetTotal} size="sm" />
            </div>
          </div>
          {active.status === "active" && (
            <button
              onClick={() => {
                onClose(active.id);
                toast.success("Calibration closed", { description: active.name });
              }}
              className="rounded-medium bg-background-brand-bold px-150 py-050 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed"
            >
              Close variance
            </button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-body-small">
            <thead className="bg-surface-sunken text-body-small text-text-subtlest">
              <tr>
                <th className="px-150 py-100 text-left font-medium">Reviewer</th>
                {defaultRubric.sections.map((s) => (
                  <th key={s.id} className="px-150 py-100 text-left font-medium">
                    {s.label}
                  </th>
                ))}
                <th className="px-150 py-100 text-right font-medium">Total</th>
                <th className="px-150 py-100 text-right font-medium">Δ vs target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <tr className="bg-background-brand-subtlest/40">
                <td className="px-150 py-100 font-semibold text-text">Target</td>
                {defaultRubric.sections.map((s) => {
                  const sub = computeTotal(
                    {
                      entries: active.target.filter((e) =>
                        s.criteria.some((c) => c.id === e.criterionId),
                      ),
                    },
                    { ...defaultRubric, sections: [s] },
                  );
                  return (
                    <td key={s.id} className="px-150 py-100 text-text">
                      {sub.toFixed(0)}
                    </td>
                  );
                })}
                <td className="px-150 py-100 text-right">
                  <ScoreBand total={targetTotal} size="sm" />
                </td>
                <td className="px-150 py-100 text-right text-text-subtlest">—</td>
              </tr>
              {active.reviewers.map((r) => {
                const total = computeTotal({ entries: r.entries }, defaultRubric);
                const delta = total - targetTotal;
                const bad = Math.abs(delta) > 8;
                return (
                  <tr key={r.reviewer}>
                    <td className="px-150 py-100 font-medium text-text">{r.reviewer}</td>
                    {defaultRubric.sections.map((s) => {
                      const sub = computeTotal(
                        {
                          entries: r.entries.filter((e) =>
                            s.criteria.some((c) => c.id === e.criterionId),
                          ),
                        },
                        { ...defaultRubric, sections: [s] },
                      );
                      return (
                        <td key={s.id} className="px-150 py-100 text-text">
                          {sub.toFixed(0)}
                        </td>
                      );
                    })}
                    <td className="px-150 py-100 text-right">
                      <ScoreBand total={total} size="sm" />
                    </td>
                    <td
                      className={cn(
                        "px-150 py-100 text-right font-medium",
                        bad ? "text-text-danger-bolder" : "text-text-success-bolder",
                      )}
                    >
                      {delta > 0 ? "+" : ""}
                      {delta.toFixed(1)}
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
