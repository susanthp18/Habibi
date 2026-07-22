import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtMoney, type PaymentPlan } from "@/data/promises-seed";
import { cn } from "@/lib/utils";

interface Props {
  plan: PaymentPlan | null;
  onOpenChange: (v: boolean) => void;
}

export function PlanDetailDrawer({ plan, onOpenChange }: Props) {
  if (!plan) return null;
  const paid = plan.installments.filter((i) => i.paid).length;
  const pct = Math.round((paid / plan.installments.length) * 100);
  const paidAmt = plan.installments.filter((i) => i.paid).reduce((s, i) => s + i.amount, 0);

  return (
    <Sheet open={!!plan} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[480px]">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {plan.customerName}
            <Badge variant="outline" className="text-[10px]">{plan.id}</Badge>
          </SheetTitle>
          <SheetDescription>
            {plan.installments.length}-installment {plan.cadence} plan · owner {plan.owner}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-4">
          <div className="rounded-lg border border-[var(--border-token)] bg-surface-sunken/60 p-3">
            <div className="flex items-center justify-between text-[12px]">
              <span className="text-text-secondary">Repaid</span>
              <span className="tabular-nums font-medium text-brand-navy">
                {fmtMoney(paidAmt)} / {fmtMoney(plan.total)}
              </span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-card">
              <div className="h-full bg-brand-primary" style={{ width: `${pct}%` }} />
            </div>
            <div className="mt-1 text-[11px] text-text-muted">{paid} of {plan.installments.length} installments · {pct}%</div>
          </div>

          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Installments</div>
            <ol className="space-y-1.5">
              {plan.installments.map((i) => {
                const overdue = !i.paid && new Date(i.dueDate).getTime() < Date.now();
                return (
                  <li
                    key={i.index}
                    className={cn(
                      "flex items-center justify-between rounded border px-3 py-2 text-[12px]",
                      i.paid
                        ? "border-emerald-200 bg-emerald-50/60"
                        : overdue
                          ? "border-red-200 bg-red-50/60"
                          : "border-[var(--border-token)] bg-surface-card",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="tabular-nums font-medium text-text-secondary">#{i.index}</span>
                      <span className="text-text-primary">{fmtDate(i.dueDate)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="tabular-nums font-medium text-brand-navy">{fmtMoney(i.amount)}</span>
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10.5px] font-medium",
                          i.paid
                            ? "bg-emerald-100 text-emerald-700"
                            : overdue
                              ? "bg-red-100 text-red-700"
                              : "bg-surface-sunken text-text-secondary",
                        )}
                      >
                        {i.paid ? "Paid" : overdue ? "Overdue" : "Upcoming"}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
