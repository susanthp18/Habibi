import { useMemo, useState } from "react";

import type { BillingModelSpend } from "@/api/billing";
import { inrCompact } from "@/data/billing-seed";
import { cn } from "@/lib/utils";

type SortKey = "cost" | "calls";

/**
 * Spend grouped by the model that produced it.
 *
 * The service table beside this one cannot answer "which model is the money
 * going to": `billing_services` carries a single blended `llm_chat` row, so a
 * gpt-5 turn and a gpt-4o-mini turn land in the same bucket despite pricing
 * roughly 8x apart. This reads the per-model dimension off usage_events.
 */
export function ModelCostTable({ rows }: { rows: BillingModelSpend[] }) {
  const [sort, setSort] = useState<SortKey>("cost");

  const total = useMemo(() => rows.reduce((acc, r) => acc + r.costInr, 0), [rows]);
  const sorted = useMemo(() => {
    const arr = [...rows];
    arr.sort((a, b) => (sort === "cost" ? b.costInr - a.costInr : b.calls - a.calls));
    return arr;
  }, [rows, sort]);

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between gap-200 border-b border-border px-200 py-100">
        <div>
          <h3 className="text-body font-semibold text-text">Cost breakdown by model</h3>
          <p className="text-body-small text-text-subtle">
            Deployment for LLM, neural voice for TTS, locale for STT
          </p>
        </div>
        <div className="flex shrink-0 gap-050">
          {(["cost", "calls"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setSort(key)}
              className={cn(
                "rounded-small px-100 py-050 text-body-small transition-colors",
                sort === key
                  ? "bg-background-brand-subtlest font-medium text-text-brand"
                  : "text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {key === "cost" ? "By spend" : "By calls"}
            </button>
          ))}
        </div>
      </div>

      {sorted.length === 0 ? (
        <p className="px-200 py-200 text-body-small text-text-subtlest">
          No per-model usage in this window. Calls handled before per-call
          metering was enabled carry no model dimension.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-body-small">
            <thead>
              <tr className="border-b border-border text-left font-semibold text-text-subtlest">
                <th className="px-200 py-100">Model</th>
                <th className="px-200 py-100">Service</th>
                <th className="px-200 py-100 text-right">Usage</th>
                <th className="px-200 py-100 text-right">Calls</th>
                <th className="px-200 py-100 text-right">Spend</th>
                <th className="px-200 py-100 text-right">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sorted.map((r) => {
                const share = total > 0 ? (r.costInr / total) * 100 : 0;
                return (
                  <tr key={`${r.serviceId}-${r.model}`} className="hover:bg-surface-sunken">
                    <td className="px-200 py-100">
                      <div className="flex items-center gap-075">
                        <span
                          aria-hidden
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: r.color }}
                        />
                        <span className="font-mono text-text">{r.model}</span>
                      </div>
                    </td>
                    <td className="px-200 py-100 text-text-subtle">{r.serviceName}</td>
                    <td className="px-200 py-100 text-right font-mono text-text-subtle">
                      {r.units >= 100
                        ? Math.round(r.units).toLocaleString("en-IN")
                        : r.units.toFixed(2)}{" "}
                      {r.unit}
                    </td>
                    <td className="px-200 py-100 text-right font-mono text-text-subtle">
                      {r.calls.toLocaleString("en-IN")}
                    </td>
                    <td className="px-200 py-100 text-right font-mono text-text">
                      {inrCompact(r.costInr)}
                    </td>
                    <td className="px-200 py-100 text-right font-mono text-text-subtlest">
                      {share.toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
