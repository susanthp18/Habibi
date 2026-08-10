import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtMoney, type PaymentPlan } from "@/data/promises-seed";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

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
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[25rem]">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-100">
            {plan.customerName}
            <Badge variant="outline" className="text-body-small">{plan.id}</Badge>
          </SheetTitle>
          <SheetDescription>
            {plan.installments.length}-installment {plan.cadence} plan · owner {plan.owner}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-200 space-y-200">
          <div className="rounded-large border border-border bg-surface-sunken/60 p-150">
            <div className="flex items-center justify-between text-body-small">
              <span className="text-text-subtle">Repaid</span>
              <span className="tabular-nums font-medium text-text">
                {fmtMoney(paidAmt)} / {fmtMoney(plan.total)}
              </span>
            </div>
            <div className="mt-100 h-100 overflow-hidden rounded-full bg-surface">
              <div className="h-full bg-background-brand-bold" style={{ width: `${pct}%` }} />
            </div>
            <div className="mt-050 text-body-small text-text-subtlest">{paid} of {plan.installments.length} installments · {pct}%</div>
          </div>

          <div>
            <div className="mb-100 text-body-small font-semibold text-text-subtlest">Installments</div>
            <ol className="space-y-075">
              {plan.installments.map((i) => {
                const overdue = !i.paid && new Date(i.dueDate).getTime() < Date.now();
                return (
                  <li
                    key={i.index}
                    className={cn(
                      "flex items-center justify-between rounded border px-150 py-100 text-body-small",
                      i.paid
                        ? "border-border-success-subtle bg-background-success-subtler/60"
                        : overdue
                          ? "border-border-danger-subtle bg-background-danger-subtler/60"
                          : "border-border bg-surface",
                    )}
                  >
                    <div className="flex items-center gap-100">
                      <span className="tabular-nums font-medium text-text-subtle">#{i.index}</span>
                      <span className="text-text">{fmtDate(i.dueDate)}</span>
                    </div>
                    <div className="flex items-center gap-100">
                      <span className="tabular-nums font-medium text-text">{fmtMoney(i.amount)}</span>
                      <Lozenge tone={i.paid ? "success" : overdue ? "danger" : "neutral"}>
                        {i.paid ? "Paid" : overdue ? "Overdue" : "Upcoming"}
                      </Lozenge>
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
