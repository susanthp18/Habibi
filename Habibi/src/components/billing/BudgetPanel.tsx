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
    <div className="flex h-full min-h-[17.5rem] max-h-full flex-col overflow-hidden rounded-large border border-border bg-surface p-200">
      <div className="mb-100 flex shrink-0 items-center justify-between">
        <div>
          <h3 className="text-body font-semibold text-text">Budgets & alerts</h3>
          <p className="text-body-small text-text-subtle">Monthly caps and threshold rules per environment</p>
        </div>
        <Bell className="h-4 w-4 text-text-brand" />
      </div>

      <div className="min-h-0 flex-1 space-y-150 overflow-y-auto pr-050">
        {budgets.map((b) => {
          const spent = spendByEnv[b.env] ?? 0;
          const pct = b.monthlyCapInr ? Math.round((spent / b.monthlyCapInr) * 100) : 0;
          const tone = pct < 70 ? "emerald" : pct < 90 ? "amber" : "rose";
          return (
            <div key={b.id} className="rounded-medium border border-border p-150">
              <div className="flex items-center justify-between text-body-small">
                <div className="font-semibold capitalize text-text">
                  {b.env === "production" ? "Prod" : "Sandbox"}
                </div>
                <div className="text-text-subtlest">
                  <span
                    className={cn(
                      "font-semibold",
                      tone === "emerald" && "text-text-success",
                      tone === "amber" && "text-text-warning",
                      tone === "rose" && "text-text-danger",
                    )}
                  >
                    {inrCompact(spent)}
                  </span>
                  <span className="mx-050">/</span>
                  {inrCompact(b.monthlyCapInr)} · {pct}%
                </div>
              </div>
              <div className="mt-075 h-100 w-full overflow-hidden rounded-full bg-surface-sunken">
                <div
                  className={cn(
                    "h-full rounded-full",
                    tone === "emerald" && "bg-background-success-bold",
                    tone === "amber" && "bg-background-warning-bold",
                    tone === "rose" && "bg-background-danger-bold",
                  )}
                  style={{ width: `${Math.min(100, pct)}%` }}
                />
              </div>

              <div className="mt-150 space-y-075">
                {b.rules.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center gap-100 rounded border border-border bg-surface px-100 py-075 text-body-small"
                  >
                    <span
                      className={cn(
                        "rounded px-075 py-025 font-mono font-semibold text-body-small",
                        r.severity === "info" && "bg-background-brand-subtlest text-text-brand",
                        r.severity === "warn" && "bg-background-warning-subtler text-text-warning-bolder",
                        r.severity === "critical" && "bg-background-danger-subtler text-text-danger-bolder",
                      )}
                    >
                      ≥ {r.threshold}%
                    </span>
                    <span className="flex-1 truncate">{r.action}</span>
                    <span className="max-w-[7.5rem] truncate text-text-subtlest">
                      {r.channels.join(" · ")}
                    </span>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-300 w-300"
                      disabled={saving}
                      onClick={() => setDialogFor({ budgetId: b.id, env: b.env, rule: r })}
                      aria-label="Edit rule"
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-300 w-300 text-text-danger hover:text-text-danger-bolder"
                      disabled={saving}
                      onClick={() => {
                        if (window.confirm(`Delete rule "${r.action}"?`)) {
                          void (async () => {
                            try {
                              await onDeleteRule(b.id, r.id);
                            } catch {
                              // Parent toasts the error; keep the row clickable.
                            }
                          })();
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
                  className="h-7 w-full justify-start text-body-small"
                  disabled={saving}
                  onClick={() => setDialogFor({ budgetId: b.id, env: b.env, rule: null })}
                >
                  <Plus className="mr-050 h-3 w-3" /> Add threshold rule
                </Button>
              </div>
            </div>
          );
        })}

        <div className="rounded-medium border border-border p-150">
          <div className="mb-100 flex items-center gap-075 text-body-small font-semibold text-text">
            <AlertTriangle className="h-3.5 w-3.5 text-icon-warning" /> Recent alerts
          </div>
          {alerts.length === 0 ? (
            <p className="text-body-small text-text-subtlest">No recent budget alerts.</p>
          ) : (
            <ul className="space-y-050 text-body-small">
              {alerts.map((a) => (
                <li key={a.id} className="flex items-baseline gap-100 text-text-subtle">
                  <span className="w-[6.875rem] shrink-0 font-mono text-body-small text-text-subtlest">{a.when}</span>
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
