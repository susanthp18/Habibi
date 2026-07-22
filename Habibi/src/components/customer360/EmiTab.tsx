import type { Customer, EmiRow, EmiStatus } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<EmiStatus, { chip: string; dot: string; label: string }> = {
  paid: { chip: "bg-success-bg text-success", dot: "bg-success", label: "Paid" },
  upcoming: { chip: "bg-surface-sunken text-text-secondary", dot: "bg-text-muted", label: "Upcoming" },
  overdue: { chip: "bg-danger-bg text-danger", dot: "bg-danger", label: "Overdue" },
  partial: { chip: "bg-warning-bg text-warning", dot: "bg-warning", label: "Partial" },
};

export function EmiTab({ customer }: { customer: Customer }) {
  const paid = customer.emi.filter((e) => e.status === "paid").length;
  const total = customer.emi.length;
  const pct = (paid / total) * 100;

  return (
    <div className="space-y-4">
      {/* Progress */}
      <div className="rounded-lg border border-border bg-surface-card p-4">
        <div className="mb-2 flex items-center justify-between text-sm">
          <div>
            <div className="font-semibold text-brand-navy">Repayment progress</div>
            <div className="text-xs text-text-secondary">
              {paid} of {total} installments paid
            </div>
          </div>
          <div className="text-lg font-semibold text-brand-primary tabular">{pct.toFixed(0)}%</div>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div className="h-full rounded-full bg-brand-primary" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Timeline strip */}
      <div className="rounded-lg border border-border bg-surface-card p-4">
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">Installment timeline</div>
        <div className="flex items-center gap-1 overflow-x-auto pb-1">
          {customer.emi.map((e) => {
            const t = STATUS_TONE[e.status];
            return (
              <div key={e.id} className="flex flex-1 min-w-[52px] flex-col items-center gap-1" title={`EMI #${e.index} · ${fmtDate(e.dueDate)}`}>
                <div className={cn("h-2 w-full rounded-full", t.dot)} />
                <div className="text-[10px] text-text-muted tabular">#{e.index}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          {(Object.keys(STATUS_TONE) as EmiStatus[]).map((s) => (
            <span key={s} className="inline-flex items-center gap-1 text-text-secondary">
              <span className={cn("h-2 w-2 rounded-full", STATUS_TONE[s].dot)} />
              {STATUS_TONE[s].label}
            </span>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="overflow-hidden rounded-lg border border-border bg-surface-card">
        <table className="w-full text-sm">
          <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-2 text-left font-medium">#</th>
              <th className="px-4 py-2 text-left font-medium">Due date</th>
              <th className="px-4 py-2 text-right font-medium">Amount</th>
              <th className="px-4 py-2 text-left font-medium">Paid on</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-right font-medium">Balance carried</th>
            </tr>
          </thead>
          <tbody>
            {customer.emi.map((r) => (
              <EmiListRow key={r.id} r={r} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmiListRow({ r }: { r: EmiRow }) {
  const t = STATUS_TONE[r.status];
  return (
    <tr className="border-t border-border hover:bg-brand-tint/30">
      <td className="px-4 py-2.5 text-sm font-medium text-text-primary tabular">#{r.index}</td>
      <td className="px-4 py-2.5 text-sm text-text-secondary tabular">{fmtDate(r.dueDate)}</td>
      <td className="px-4 py-2.5 text-right text-sm font-medium text-brand-navy tabular">{fmtMoney(r.amount)}</td>
      <td className="px-4 py-2.5 text-sm text-text-secondary tabular">
        {r.paidOn ? (
          <>
            {fmtDate(r.paidOn)}
            {r.paidAmount && r.paidAmount !== r.amount && <span className="ml-1 text-[10px] text-warning">· {fmtMoney(r.paidAmount)}</span>}
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="px-4 py-2.5">
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", t.chip)}>{t.label}</span>
      </td>
      <td className="px-4 py-2.5 text-right text-sm text-text-secondary tabular">{fmtMoney(r.balanceCarried)}</td>
    </tr>
  );
}
