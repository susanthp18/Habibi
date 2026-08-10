import { useMemo, useState } from "react";
import type { Customer, LedgerEntry, LedgerType } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { StatusChip, ledgerTypeTone } from "./StatusChip";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<LedgerType, string> = {
  charge: "Charge",
  payment: "Payment",
  fee: "Fee",
  adjustment: "Adjustment",
  waiver: "Waiver",
};

const TYPES: LedgerType[] = ["charge", "payment", "fee", "adjustment", "waiver"];

export function LedgerTab({ customer }: { customer: Customer }) {
  const [enabled, setEnabled] = useState<Record<LedgerType, boolean>>({
    charge: true,
    payment: true,
    fee: true,
    adjustment: true,
    waiver: true,
  });
  const [range, setRange] = useState<90 | 180 | 365>(180);

  const summary = useMemo(() => {
    const principal = customer.ledger.filter((r) => r.type === "charge").reduce((s, r) => s + r.amount, 0);
    const fees = customer.ledger.filter((r) => r.type === "fee").reduce((s, r) => s + r.amount, 0);
    const payments = customer.ledger.filter((r) => r.type === "payment").reduce((s, r) => s + Math.abs(r.amount), 0);
    const lastPayment = customer.ledger.find((r) => r.type === "payment");
    const total = customer.outstanding;
    return { principal, fees, payments, lastPayment, total };
  }, [customer]);

  const rows = useMemo(() => {
    const cutoff = Date.now() - range * 86400_000;
    return customer.ledger.filter((r) => enabled[r.type] && new Date(r.date).getTime() >= cutoff);
  }, [customer.ledger, enabled, range]);

  return (
    <div className="space-y-200">
      <div className="grid grid-cols-2 gap-150 md:grid-cols-5">
        <StatTile label="Principal" value={fmtMoney(summary.principal)} />
        <StatTile label="Fees" value={fmtMoney(summary.fees)} tone="warning" />
        <StatTile label="Payments received" value={fmtMoney(summary.payments)} tone="success" />
        <StatTile label="Outstanding" value={fmtMoney(summary.total)} tone="brand" />
        <StatTile label="Last payment" value={summary.lastPayment ? fmtDate(summary.lastPayment.date) : "—"} />
      </div>

      <div className="flex flex-wrap items-center gap-100 rounded-large border border-border bg-surface p-100">
        <span className="text-body-small font-semibold text-text-subtle">Types</span>
        {TYPES.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setEnabled((e) => ({ ...e, [t]: !e[t] }))}
            className={cn(
              "rounded-medium border px-100 py-025 text-body-small font-medium capitalize",
              enabled[t]
                ? "border-border-brand bg-background-brand-bold text-white"
                : "border-border bg-surface text-text-subtle hover:bg-background-brand-subtlest hover:text-text-brand",
            )}
          >
            {TYPE_LABEL[t]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-050">
          <span className="text-body-small text-text-subtle">Range</span>
          {[90, 180, 365].map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r as 90 | 180 | 365)}
              className={cn(
                "rounded-medium px-100 py-025 text-body-small font-medium",
                range === r ? "bg-background-brand-boldest text-white" : "text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {r}d
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-large border border-border bg-surface">
        <table className="w-full text-sm">
          <thead className="bg-surface-sunken text-body-small text-text-subtle">
            <tr>
              <th className="px-200 py-100 text-left font-medium">Date</th>
              <th className="px-200 py-100 text-left font-medium">Description</th>
              <th className="px-200 py-100 text-left font-medium">Type</th>
              <th className="px-200 py-100 text-right font-medium">Amount</th>
              <th className="px-200 py-100 text-right font-medium">Balance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <LedgerRow key={r.id} r={r} />
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="px-200 py-400 text-center text-sm text-text-subtlest">
                  No entries in this window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LedgerRow({ r }: { r: LedgerEntry }) {
  const isCredit = r.amount < 0;
  return (
    <tr className="border-t border-border hover:bg-background-brand-subtlest/30">
      <td className="px-200 py-150 text-xs text-text-subtle tabular">{fmtDate(r.date)}</td>
      <td className="px-200 py-150">
        <div className="text-sm text-text">{r.description}</div>
        {r.invoiceId && <div className="text-body-small text-text-subtlest">Invoice · {r.invoiceId}</div>}
      </td>
      <td className="px-200 py-150">
        <StatusChip label={TYPE_LABEL[r.type]} tone={ledgerTypeTone(r.type)} />
      </td>
      <td className={cn("px-200 py-150 text-right text-sm font-medium tabular", isCredit ? "text-text-success" : "text-text")}>
        {fmtMoney(r.amount)}
      </td>
      <td className="px-200 py-150 text-right text-sm text-text-subtle tabular">{fmtMoney(r.balance)}</td>
    </tr>
  );
}

function StatTile({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "brand" | "success" | "warning" }) {
  const toneClass =
    tone === "brand"
      ? "text-text-brand"
      : tone === "success"
        ? "text-text-success"
        : tone === "warning"
          ? "text-text-warning"
          : "text-text";
  return (
    <div className="rounded-large border border-border bg-surface p-150">
      <div className="text-body-small text-text-subtle">{label}</div>
      <div className={cn("mt-025 text-lg font-semibold tabular", toneClass)}>{value}</div>
    </div>
  );
}
