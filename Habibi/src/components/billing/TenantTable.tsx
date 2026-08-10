import { ArrowDown, ArrowUp } from "lucide-react";
import type { BillingTenantBreakdown } from "@/api/billing";
import { inrCompact } from "@/data/billing-seed";
import { cn } from "@/lib/utils";

export function TenantTable({ rows }: { rows: BillingTenantBreakdown[] }) {
  return (
    <div className="flex flex-col rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-100">
        <h3 className="text-body font-semibold text-text">Per-tenant breakdown</h3>
        <p className="text-body-small text-text-subtle">Spend and unit economics per client account</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-body-small">
          <thead>
            <tr className="border-b border-border text-left text-body-small font-semibold text-text-subtlest">
              <th className="px-200 py-100">Tenant</th>
              <th className="px-150 py-100 text-right">Resolved calls</th>
              <th className="px-150 py-100 text-right">AHT</th>
              <th className="px-150 py-100 text-right">Spend</th>
              <th className="px-150 py-100 text-right">Cost / call</th>
              <th className="px-150 py-100 text-right">Δ</th>
              <th className="px-150 py-100 text-right">Budget</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const delta =
                r.spendPrev > 0 ? ((r.spend - r.spendPrev) / r.spendPrev) * 100 : r.spend > 0 ? 100 : 0;
              return (
                <tr
                  key={r.id}
                  className={cn(
                    "border-b border-border transition-colors hover:bg-surface-sunken",
                    r.budgetPct > 100 && "bg-background-danger",
                  )}
                >
                  <td className="px-200 py-150 font-medium text-text">{r.name}</td>
                  <td className="px-150 py-150 text-right font-mono">
                    {r.resolvedCalls.toLocaleString("en-IN")}
                  </td>
                  <td className="px-150 py-150 text-right font-mono text-text-subtle">
                    {Math.floor(r.ahtSec / 60)}m {r.ahtSec % 60}s
                  </td>
                  <td className="px-150 py-150 text-right font-semibold text-text">
                    {inrCompact(r.spend)}
                  </td>
                  <td className="px-150 py-150 text-right font-mono">₹{r.costPerCall.toFixed(1)}</td>
                  <td className="px-150 py-150 text-right">
                    <span
                      className={cn(
                        "inline-flex items-center gap-025 rounded px-075 py-025 text-body-small font-semibold",
                        delta >= 0 ? "bg-background-danger-subtler text-text-danger-bolder" : "bg-background-success-subtler text-text-success-bolder",
                      )}
                    >
                      {delta >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                      {Math.abs(delta).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-150 py-150">
                    <div className="ml-auto flex items-center justify-end gap-100">
                      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                        <div
                          className={cn(
                            "h-full rounded-full",
                            r.budgetPct < 70 && "bg-background-success-bold",
                            r.budgetPct >= 70 && r.budgetPct < 100 && "bg-background-warning-bold",
                            r.budgetPct >= 100 && "bg-background-danger-bold",
                          )}
                          style={{ width: `${Math.min(100, r.budgetPct)}%` }}
                        />
                      </div>
                      <span className="w-500 text-right text-body-small text-text-subtlest">
                        {Math.round(r.budgetPct)}%
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
