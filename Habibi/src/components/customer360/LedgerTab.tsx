import { useMemo, useState } from "react";
import type { Customer, LedgerEntry, LedgerType } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { StatusChip, ledgerTypeTone } from "./StatusChip";
import { cn } from "@/lib/utils";
import { FilterTable, type FilterChip, type FilterTableColumn } from "@/components/records/FilterTable";

const TYPE_LABEL: Record<LedgerType, string> = {
  charge: "Charge",
  payment: "Payment",
  fee: "Fee",
  adjustment: "Adjustment",
  waiver: "Waiver",
};

const TYPE_DOT: Record<LedgerType, string> = {
  charge: "var(--icon-accent-blue)",
  payment: "var(--icon-accent-green)",
  fee: "var(--icon-accent-orange)",
  adjustment: "var(--icon-accent-gray)",
  waiver: "var(--icon-accent-teal)",
};

const TYPES: LedgerType[] = ["charge", "payment", "fee", "adjustment", "waiver"];

export function LedgerTab({ customer }: { customer: Customer }) {
  const [range, setRange] = useState<90 | 180 | 365>(180);

  const summary = useMemo(() => {
    const principal = customer.ledger.filter((r) => r.type === "charge").reduce((s, r) => s + r.amount, 0);
    const fees = customer.ledger.filter((r) => r.type === "fee").reduce((s, r) => s + r.amount, 0);
    const payments = customer.ledger.filter((r) => r.type === "payment").reduce((s, r) => s + Math.abs(r.amount), 0);
    const lastPayment = customer.ledger.find((r) => r.type === "payment");
    const total = customer.outstanding;
    return { principal, fees, payments, lastPayment, total };
  }, [customer]);

  const ranged = useMemo(() => {
    const cutoff = Date.now() - range * 86400_000;
    return customer.ledger.filter((r) => new Date(r.date).getTime() >= cutoff);
  }, [customer.ledger, range]);

  const chips = useMemo<FilterChip<LedgerType>[]>(() => {
    const counts = Object.fromEntries(TYPES.map((t) => [t, 0])) as Record<LedgerType, number>;
    for (const r of ranged) counts[r.type] += 1;
    return [
      { key: "all", label: "All", count: ranged.length },
      ...TYPES.map((t) => ({ key: t, label: TYPE_LABEL[t], dot: TYPE_DOT[t], count: counts[t] })),
    ];
  }, [ranged]);

  const columns = useMemo<FilterTableColumn<LedgerEntry>[]>(
    () => [
      {
        id: "date",
        header: "Date",
        width: "0.9fr",
        cell: (r) => <span className="text-body-small tabular-nums text-text-subtle">{fmtDate(r.date)}</span>,
      },
      {
        id: "description",
        header: "Description",
        width: "1.8fr",
        cell: (r) => (
          <div className="min-w-0">
            <div className="truncate text-body text-text">{r.description}</div>
            {r.invoiceId ? (
              <div className="truncate text-body-small text-text-subtlest">Invoice · {r.invoiceId}</div>
            ) : null}
          </div>
        ),
      },
      {
        id: "type",
        header: "Type",
        width: "0.8fr",
        cell: (r) => <StatusChip label={TYPE_LABEL[r.type]} tone={ledgerTypeTone(r.type)} />,
      },
      {
        id: "amount",
        header: "Amount",
        width: "0.8fr",
        className: "text-right",
        cell: (r) => (
          <span
            className={cn(
              "text-body font-medium tabular-nums",
              r.amount < 0 ? "text-text-success" : "text-text",
            )}
          >
            {fmtMoney(r.amount)}
          </span>
        ),
      },
      {
        id: "balance",
        header: "Balance",
        width: "0.8fr",
        className: "text-right",
        cell: (r) => (
          <span className="text-body tabular-nums text-text-subtle">{fmtMoney(r.balance)}</span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-200">
      <div className="grid grid-cols-2 gap-150 md:grid-cols-5">
        <StatTile label="Principal" value={fmtMoney(summary.principal)} />
        <StatTile label="Fees" value={fmtMoney(summary.fees)} tone="warning" />
        <StatTile label="Payments received" value={fmtMoney(summary.payments)} tone="success" />
        <StatTile label="Outstanding" value={fmtMoney(summary.total)} tone="brand" />
        <StatTile label="Last payment" value={summary.lastPayment ? fmtDate(summary.lastPayment.date) : "—"} />
      </div>

      <div className="flex items-center justify-end gap-050">
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

      <FilterTable
        rows={ranged}
        getRowId={(r) => r.id}
        getStatus={(r) => r.type}
        chips={chips}
        columns={columns}
        emptyMessage="No entries in this window."
        ariaLabel="Account ledger"
      />
    </div>
  );
}

function StatTile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "brand" | "success" | "warning";
}) {
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
