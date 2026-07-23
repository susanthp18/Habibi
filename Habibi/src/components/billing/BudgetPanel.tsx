import { useState } from "react";
import { AlertTriangle, Bell, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BudgetRule } from "@/data/billing-seed";
import { inrCompact } from "@/data/billing-seed";
import type { BillingBudget } from "@/api/billing";
import type { AlertEvent } from "@/data/billing-seed";
import { cn } from "@/lib/utils";
import { BudgetRuleDialog } from "./BudgetRuleDialog";

export function BudgetPanel({
  budgets,
  spendByEnv,
  alerts,
  onSaveRule,
  onDeleteRule,
  saving,
}: {
  budgets: BillingBudget[];
  spendByEnv: Record<string, number>;
  alerts: AlertEvent[];
  onSaveRule: (budgetId: string, rule: BudgetRule | Omit<BudgetRule, "id">) => Promise<void>;
  onDeleteRule: (budgetId: string, ruleId: string) => Promise<void>;
  saving?: boolean;
}) {
  const [dialogFor, setDialogFor] = useState<{
    budgetId: string;
    env: BillingBudget["env"];
    rule: BudgetRule | null;
  } | null>(null);

  return (
    <div className="flex h-full min-h-[280px] max-h-full flex-col overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
      <div className="mb-2 flex shrink-0 items-center justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-brand-navy">Budgets & alerts</h3>
          <p className="text-[11px] text-text-secondary">Monthly caps and threshold rules per environment</p>
        </div>
        <Bell className="h-4 w-4 text-brand-primary" />
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {budgets.map((b) => {
          const spent = spendByEnv[b.env] ?? 0;
          const pct = b.monthlyCapInr ? Math.round((spent / b.monthlyCapInr) * 100) : 0;
          const tone = pct < 70 ? "emerald" : pct < 90 ? "amber" : "rose";
          return (
            <div key={b.id} className="rounded-md border border-[var(--border-token)] p-3">
              <div className="flex items-center justify-between text-[12px]">
                <div className="font-semibold capitalize text-brand-navy">
                  {b.env === "production" ? "Prod" : "Sandbox"}
                </div>
                <div className="text-text-muted">
                  <span
                    className={cn(
                      "font-semibold",
                      tone === "emerald" && "text-emerald-600",
                      tone === "amber" && "text-amber-600",
                      tone === "rose" && "text-rose-600",
                    )}
                  >
                    {inrCompact(spent)}
                  </span>
                  <span className="mx-1">/</span>
                  {inrCompact(b.monthlyCapInr)} · {pct}%
                </div>
              </div>
              <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
                <div
                  className={cn(
                    "h-full rounded-full",
                    tone === "emerald" && "bg-emerald-500",
                    tone === "amber" && "bg-amber-500",
                    tone === "rose" && "bg-rose-500",
                  )}
                  style={{ width: `${Math.min(100, pct)}%` }}
                />
              </div>

              <div className="mt-3 space-y-1.5">
                {b.rules.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center gap-2 rounded border border-[var(--border-token)] bg-surface-app px-2 py-1.5 text-[11.5px]"
                  >
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 font-mono font-semibold text-[10px]",
                        r.severity === "info" && "bg-brand-tint text-brand-primary-dark",
                        r.severity === "warn" && "bg-amber-100 text-amber-700",
                        r.severity === "critical" && "bg-rose-100 text-rose-700",
                      )}
                    >
                      ≥ {r.threshold}%
                    </span>
                    <span className="flex-1 truncate">{r.action}</span>
                    <span className="max-w-[120px] truncate text-text-muted">
                      {r.channels.join(" · ")}
                    </span>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6"
                      disabled={saving}
                      onClick={() => setDialogFor({ budgetId: b.id, env: b.env, rule: r })}
                      aria-label="Edit rule"
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 text-rose-600 hover:text-rose-700"
                      disabled={saving}
                      onClick={() => {
                        if (window.confirm(`Delete rule "${r.action}"?`)) {
                          void onDeleteRule(b.id, r.id);
                        }
                      }}
                      aria-label="Delete rule"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-full justify-start text-[11.5px]"
                  disabled={saving}
                  onClick={() => setDialogFor({ budgetId: b.id, env: b.env, rule: null })}
                >
                  <Plus className="mr-1 h-3 w-3" /> Add threshold rule
                </Button>
              </div>
            </div>
          );
        })}

        <div className="rounded-md border border-[var(--border-token)] p-3">
          <div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold text-brand-navy">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500" /> Recent alerts
          </div>
          {alerts.length === 0 ? (
            <p className="text-[11.5px] text-text-muted">No recent budget alerts.</p>
          ) : (
            <ul className="space-y-1 text-[11.5px]">
              {alerts.map((a) => (
                <li key={a.id} className="flex items-baseline gap-2 text-text-secondary">
                  <span className="w-[110px] shrink-0 font-mono text-[10.5px] text-text-muted">{a.when}</span>
                  <span>{a.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <BudgetRuleDialog
        open={!!dialogFor}
        onOpenChange={(v) => !v && setDialogFor(null)}
        rule={dialogFor?.rule ?? null}
        onSave={async (r) => {
          if (!dialogFor) return;
          const payload = dialogFor.rule
            ? r
            : { threshold: r.threshold, channels: r.channels, action: r.action, severity: r.severity };
          await onSaveRule(dialogFor.budgetId, payload);
          setDialogFor(null);
        }}
        onDelete={
          dialogFor?.rule
            ? async () => {
                if (!dialogFor?.rule) return;
                await onDeleteRule(dialogFor.budgetId, dialogFor.rule.id);
                setDialogFor(null);
              }
            : undefined
        }
      />
    </div>
  );
}
