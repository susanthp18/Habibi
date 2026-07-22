import { ArrowDown, ArrowUp } from "lucide-react";
import { TENANTS, inrCompact, type DayPoint } from "@/data/billing-seed";
import { cn } from "@/lib/utils";

export function TenantTable({
  current,
  previous,
}: {
  current: DayPoint[];
  previous: DayPoint[];
}) {
  const total = current.reduce((s, r) => s + Object.values(r.values).reduce((a, b) => a + b, 0), 0);
  const prevTotal = previous.reduce((s, r) => s + Object.values(r.values).reduce((a, b) => a + b, 0), 0);

  const rows = TENANTS.map((t) => {
    const spend = total * t.spendShare;
    const prev = prevTotal * t.spendShare * (0.9 + Math.random() * 0.15);
    const delta = prev > 0 ? ((spend - prev) / prev) * 100 : 0;
    const cpc = t.resolvedCalls > 0 ? spend / t.resolvedCalls : 0;
    const budgetPct = t.budgetInr > 0 ? Math.round((spend / t.budgetInr) * 100) : 0;
    return { t, spend, delta, cpc, budgetPct };
  });

  return (
    <div className="flex flex-col rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-4 py-2">
        <h3 className="text-[13px] font-semibold text-brand-navy">Per-tenant breakdown</h3>
        <p className="text-[11px] text-text-secondary">Spend and unit economics per client account</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--border-token)] text-left text-[10.5px] font-semibold uppercase tracking-wider text-text-muted">
              <th className="px-4 py-2">Tenant</th>
              <th className="px-3 py-2 text-right">Resolved calls</th>
              <th className="px-3 py-2 text-right">AHT</th>
              <th className="px-3 py-2 text-right">Spend</th>
              <th className="px-3 py-2 text-right">Cost / call</th>
              <th className="px-3 py-2 text-right">Δ</th>
              <th className="px-3 py-2">Budget</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ t, spend, delta, cpc, budgetPct }) => (
              <tr
                key={t.id}
                className={cn(
                  "border-b border-[var(--border-token)] transition-colors hover:bg-surface-sunken",
                  budgetPct > 100 && "bg-rose-50/60",
                )}
              >
                <td className="px-4 py-2.5 font-medium text-brand-navy">{t.name}</td>
                <td className="px-3 py-2.5 text-right font-mono">
                  {t.resolvedCalls.toLocaleString("en-IN")}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-text-secondary">
                  {Math.floor(t.ahtSec / 60)}m {t.ahtSec % 60}s
                </td>
                <td className="px-3 py-2.5 text-right font-semibold text-brand-navy">{inrCompact(spend)}</td>
                <td className="px-3 py-2.5 text-right font-mono">₹{cpc.toFixed(1)}</td>
                <td className="px-3 py-2.5 text-right">
                  <span
                    className={cn(
                      "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10.5px] font-semibold",
                      delta >= 0 ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700",
                    )}
                  >
                    {delta >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                    {Math.abs(delta).toFixed(1)}%
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          budgetPct < 70 && "bg-emerald-500",
                          budgetPct >= 70 && budgetPct < 100 && "bg-amber-500",
                          budgetPct >= 100 && "bg-rose-500",
                        )}
                        style={{ width: `${Math.min(100, budgetPct)}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-[10.5px] text-text-muted">{budgetPct}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
