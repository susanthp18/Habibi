import { useMemo, useState } from "react";
import type { Customer, LedgerEntry, LedgerType } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<LedgerType, string> = {
  charge: "Charge",
  payment: "Payment",
  fee: "Fee",
  adjustment: "Adjustment",
  waiver: "Waiver",
};

const TYPE_TONE: Record<LedgerType, string> = {
  charge: "bg-brand-tint text-brand-primary-dark",
  payment: "bg-success-bg text-success",
  fee: "bg-warning-bg text-warning",
  adjustment: "bg-surface-sunken text-text-secondary",
  waiver: "bg-brand-tint text-brand-primary-dark",
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
    <div className="space-y-4">
      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Principal" value={fmtMoney(summary.principal)} />
        <StatTile label="Fees" value={fmtMoney(summary.fees)} tone="warning" />
        <StatTile label="Payments received" value={fmtMoney(summary.payments)} tone="success" />
        <StatTile label="Outstanding" value={fmtMoney(summary.total)} tone="brand" />
        <StatTile label="Last payment" value={summary.lastPayment ? fmtDate(summary.lastPayment.date) : "—"} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface-card p-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">Types</span>
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setEnabled((e) => ({ ...e, [t]: !e[t] }))}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
              enabled[t]
                ? "border-brand-primary bg-brand-primary text-white"
                : "border-border bg-surface-card text-text-secondary hover:bg-brand-tint hover:text-brand-primary-dark",
            )}
          >
            {TYPE_LABEL[t]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          <span className="text-[11px] text-text-secondary">Range</span>
          {[90, 180, 365].map((r) => (
            <button
              key={r}
              onClick={() => setRange(r as 90 | 180 | 365)}
              className={cn(
                "rounded-md px-2 py-0.5 text-[11px] font-medium",
                range === r ? "bg-brand-navy text-white" : "text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {r}d
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-border bg-surface-card">
        <table className="w-full text-sm">
          <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Date</th>
              <th className="px-4 py-2 text-left font-medium">Description</th>
              <th className="px-4 py-2 text-left font-medium">Type</th>
              <th className="px-4 py-2 text-right font-medium">Amount</th>
              <th className="px-4 py-2 text-right font-medium">Balance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <LedgerRow key={r.id} r={r} />
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-text-muted">
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
    <tr className="border-t border-border hover:bg-brand-tint/30">
      <td className="px-4 py-2.5 text-xs text-text-secondary tabular">{fmtDate(r.date)}</td>
      <td className="px-4 py-2.5">
        <div className="text-sm text-text-primary">{r.description}</div>
        {r.invoiceId && <div className="text-[10px] text-text-muted">Invoice · {r.invoiceId}</div>}
      </td>
      <td className="px-4 py-2.5">
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase", TYPE_TONE[r.type])}>{TYPE_LABEL[r.type]}</span>
      </td>
      <td className={cn("px-4 py-2.5 text-right text-sm font-medium tabular", isCredit ? "text-success" : "text-brand-navy")}>{fmtMoney(r.amount)}</td>
      <td className="px-4 py-2.5 text-right text-sm text-text-secondary tabular">{fmtMoney(r.balance)}</td>
    </tr>
  );
}

function StatTile({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "brand" | "success" | "warning" }) {
  const toneClass = tone === "brand"
    ? "text-brand-primary"
    : tone === "success"
    ? "text-success"
    : tone === "warning"
    ? "text-warning"
    : "text-brand-navy";
  return (
    <div className="rounded-lg border border-border bg-surface-card p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</div>
      <div className={cn("mt-0.5 text-lg font-semibold tabular", toneClass)}>{value}</div>
    </div>
  );
}
