import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { fmtDate, fmtMoney, type PaymentPlan } from "@/data/promises-seed";
import { cn } from "@/lib/utils";

interface Props {
  plans: PaymentPlan[];
  onOpen: (p: PaymentPlan) => void;
}

const statusChip: Record<PaymentPlan["status"], string> = {
  on_track: "bg-emerald-50 text-emerald-700",
  slipped: "bg-orange-50 text-orange-700",
  completed: "bg-brand-tint text-brand-primary-dark",
};

export function PaymentPlansTable({ plans, onOpen }: Props) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 border-b border-[var(--border-token)] px-4 py-2.5 text-left"
      >
        {open ? <ChevronDown className="h-4 w-4 text-text-secondary" /> : <ChevronRight className="h-4 w-4 text-text-secondary" />}
        <div className="text-[13px] font-semibold text-brand-navy">Payment plans</div>
        <div className="text-[11px] text-text-muted">
          {plans.length} plan{plans.length === 1 ? "" : "s"} · {plans.filter((p) => p.status === "on_track").length} on-track ·{" "}
          {plans.filter((p) => p.status === "slipped").length} slipped
        </div>
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border-token)] text-left text-[10.5px] uppercase tracking-wider text-text-muted">
                <th className="px-4 py-2 font-semibold">Customer</th>
                <th className="px-4 py-2 font-semibold">Total</th>
                <th className="px-4 py-2 font-semibold">Installments</th>
                <th className="px-4 py-2 font-semibold">Cadence</th>
                <th className="px-4 py-2 font-semibold">Next due</th>
                <th className="px-4 py-2 font-semibold">Status</th>
                <th className="px-4 py-2 font-semibold">Owner</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p) => {
                const paid = p.installments.filter((i) => i.paid).length;
                const next = p.installments.find((i) => !i.paid);
                const pct = Math.round((paid / p.installments.length) * 100);
                return (
                  <tr
                    key={p.id}
                    onClick={() => onOpen(p)}
                    className="cursor-pointer border-b border-[var(--border-token)] last:border-0 hover:bg-surface-sunken/40"
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-brand-navy">{p.customerName}</div>
                      <div className="text-[10.5px] text-text-muted">#{p.accountTail} · {p.id}</div>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">{fmtMoney(p.total)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="tabular-nums text-text-secondary">
                          {paid}/{p.installments.length}
                        </div>
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                          <div className="h-full bg-brand-primary" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 capitalize text-text-secondary">{p.cadence}</td>
                    <td className="px-4 py-2.5 text-text-secondary">
                      {next ? fmtDate(next.dueDate) : <span className="text-text-muted">—</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={cn("rounded-full px-2 py-0.5 text-[10.5px] font-medium capitalize", statusChip[p.status])}>
                        {p.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-text-secondary">{p.owner}</td>
                  </tr>
                );
              })}
              {plans.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-text-muted">
                    No payment plans yet. Use “+ Payment plan” to build one.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
