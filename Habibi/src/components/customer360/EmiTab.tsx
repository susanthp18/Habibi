import type { Customer, EmiRow, EmiStatus } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { StatusChip, type ChipTone } from "./StatusChip";
import { cn } from "@/lib/utils";

const STATUS_META: Record<EmiStatus, { tone: ChipTone; dot: string; label: string }> = {
  paid: { tone: "success", dot: "bg-background-success", label: "Paid" },
  upcoming: { tone: "neutral", dot: "bg-text-muted", label: "Upcoming" },
  overdue: { tone: "danger", dot: "bg-background-danger", label: "Overdue" },
  partial: { tone: "warning", dot: "bg-background-warning", label: "Partial" },
};

export function EmiTab({ customer }: { customer: Customer }) {
  const paid = customer.emi.filter((e) => e.status === "paid").length;
  const total = customer.emi.length;
  const pct = (paid / total) * 100;

  return (
    <div className="space-y-200">
      {/* Progress */}
      <div className="rounded-large border border-border bg-surface p-200">
        <div className="mb-100 flex items-center justify-between text-sm">
          <div>
            <div className="font-semibold text-text">Repayment progress</div>
            <div className="text-xs text-text-subtle">
              {paid} of {total} installments paid
            </div>
          </div>
          <div className="text-lg font-semibold text-text-brand tabular">{pct.toFixed(0)}%</div>
        </div>
        <div className="h-100 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div className="h-full rounded-full bg-background-brand-bold" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Timeline strip */}
      <div className="rounded-large border border-border bg-surface p-200">
        <div className="mb-150 text-body-small font-semibold text-text-subtle">Installment timeline</div>
        <div className="flex items-center gap-050 overflow-x-auto pb-050">
          {customer.emi.map((e) => {
            const t = STATUS_META[e.status];
            return (
              <div key={e.id} className="flex flex-1 min-w-[3.25rem] flex-col items-center gap-050" title={`EMI #${e.index} · ${fmtDate(e.dueDate)}`}>
                <div className={cn("h-100 w-full rounded-full", t.dot)} />
                <div className="text-body-small text-text-subtlest tabular">#{e.index}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-150 flex flex-wrap gap-100 text-body-small">
          {(Object.keys(STATUS_META) as EmiStatus[]).map((s) => (
            <span key={s} className="inline-flex items-center gap-050 text-text-subtle">
              <span className={cn("h-100 w-100 rounded-full", STATUS_META[s].dot)} />
              {STATUS_META[s].label}
            </span>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="overflow-hidden rounded-large border border-border bg-surface">
        <table className="w-full text-sm">
          <thead className="bg-surface-sunken text-body-small text-text-subtle">
            <tr>
              <th className="px-200 py-100 text-left font-medium">#</th>
              <th className="px-200 py-100 text-left font-medium">Due date</th>
              <th className="px-200 py-100 text-right font-medium">Amount</th>
              <th className="px-200 py-100 text-left font-medium">Paid on</th>
              <th className="px-200 py-100 text-left font-medium">Status</th>
              <th className="px-200 py-100 text-right font-medium">Balance carried</th>
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
  const t = STATUS_META[r.status];
  return (
    <tr className="border-t border-border hover:bg-background-brand-subtlest/30">
      <td className="px-200 py-150 text-sm font-medium text-text tabular">#{r.index}</td>
      <td className="px-200 py-150 text-sm text-text-subtle tabular">{fmtDate(r.dueDate)}</td>
      <td className="px-200 py-150 text-right text-sm font-medium text-text tabular">{fmtMoney(r.amount)}</td>
      <td className="px-200 py-150 text-sm text-text-subtle tabular">
        {r.paidOn ? (
          <>
            {fmtDate(r.paidOn)}
            {r.paidAmount && r.paidAmount !== r.amount && <span className="ml-050 text-body-small text-text-warning">· {fmtMoney(r.paidAmount)}</span>}
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="px-200 py-150">
        <StatusChip label={t.label} tone={t.tone} />
      </td>
      <td className="px-200 py-150 text-right text-sm text-text-subtle tabular">{fmtMoney(r.balanceCarried)}</td>
    </tr>
  );
}
