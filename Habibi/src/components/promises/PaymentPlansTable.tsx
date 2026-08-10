import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { fmtDate, fmtMoney, type PaymentPlan } from "@/data/promises-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

interface Props {
  plans: PaymentPlan[];
  onOpen: (p: PaymentPlan) => void;
}

const statusChip: Record<PaymentPlan["status"], LozengeTone> = {
  on_track: "success",
  slipped: "warning",
  completed: "selected",
};

export function PaymentPlansTable({ plans, onOpen }: Props) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-large border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-100 border-b border-border px-200 py-150 text-left"
      >
        {open ? <ChevronDown className="h-4 w-4 text-text-subtle" /> : <ChevronRight className="h-4 w-4 text-text-subtle" />}
        <div className="text-body font-semibold text-text">Payment plans</div>
        <div className="text-body-small text-text-subtlest">
          {plans.length} plan{plans.length === 1 ? "" : "s"} · {plans.filter((p) => p.status === "on_track").length} on-track ·{" "}
          {plans.filter((p) => p.status === "slipped").length} slipped
        </div>
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-body-small">
            <thead>
              <tr className="border-b border-border text-left text-body-small text-text-subtlest">
                <th className="px-200 py-100 font-semibold">Customer</th>
                <th className="px-200 py-100 font-semibold">Total</th>
                <th className="px-200 py-100 font-semibold">Installments</th>
                <th className="px-200 py-100 font-semibold">Cadence</th>
                <th className="px-200 py-100 font-semibold">Next due</th>
                <th className="px-200 py-100 font-semibold">Status</th>
                <th className="px-200 py-100 font-semibold">Owner</th>
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
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-surface-sunken/40"
                  >
                    <td className="px-200 py-150">
                      <div className="font-medium text-text">{p.customerName}</div>
                      <div className="text-body-small text-text-subtlest">#{p.accountTail} · {p.id}</div>
                    </td>
                    <td className="px-200 py-150 tabular-nums">{fmtMoney(p.total)}</td>
                    <td className="px-200 py-150">
                      <div className="flex items-center gap-100">
                        <div className="tabular-nums text-text-subtle">
                          {paid}/{p.installments.length}
                        </div>
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                          <div className="h-full bg-background-brand-bold" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-200 py-150 capitalize text-text-subtle">{p.cadence}</td>
                    <td className="px-200 py-150 text-text-subtle">
                      {next ? fmtDate(next.dueDate) : <span className="text-text-subtlest">—</span>}
                    </td>
                    <td className="px-200 py-150">
                      <Lozenge tone={statusChip[p.status]} className="capitalize">
                        {p.status.replace("_", " ")}
                      </Lozenge>
                    </td>
                    <td className="px-200 py-150 text-text-subtle">{p.owner}</td>
                  </tr>
                );
              })}
              {plans.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-200 py-300 text-center text-text-subtlest">
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
