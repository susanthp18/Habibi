import { useMemo } from "react";
import type { Customer, EmiRow, EmiStatus } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { StatusChip, type ChipTone } from "./StatusChip";
import { cn } from "@/lib/utils";
import {
  FilterTable,
  type FilterChip,
  type FilterTableColumn,
} from "@/components/records/FilterTable";

const STATUS_META: Record<
  EmiStatus,
  { tone: ChipTone; dot: string; label: string; chipDot: string }
> = {
  paid: {
    tone: "success",
    dot: "bg-background-success",
    label: "Paid",
    chipDot: "var(--icon-accent-green)",
  },
  upcoming: {
    tone: "neutral",
    dot: "bg-text-muted",
    label: "Upcoming",
    chipDot: "var(--icon-accent-gray)",
  },
  overdue: {
    tone: "danger",
    dot: "bg-background-danger",
    label: "Overdue",
    chipDot: "var(--icon-accent-red)",
  },
  partial: {
    tone: "warning",
    dot: "bg-background-warning",
    label: "Partial",
    chipDot: "var(--icon-accent-yellow)",
  },
};

const STATUS_ORDER: EmiStatus[] = ["overdue", "partial", "upcoming", "paid"];

export function EmiTab({ customer }: { customer: Customer }) {
  const paid = customer.emi.filter((e) => e.status === "paid").length;
  const total = customer.emi.length;
  const pct = total ? (paid / total) * 100 : 0;

  const chips = useMemo<FilterChip<EmiStatus>[]>(() => {
    const counts = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<EmiStatus, number>;
    for (const e of customer.emi) counts[e.status] += 1;
    return [
      { key: "all", label: "All", count: customer.emi.length },
      ...STATUS_ORDER.map((s) => ({
        key: s,
        label: STATUS_META[s].label,
        dot: STATUS_META[s].chipDot,
        count: counts[s],
      })),
    ];
  }, [customer.emi]);

  const columns = useMemo<FilterTableColumn<EmiRow>[]>(
    () => [
      {
        id: "index",
        header: "#",
        width: "0.45fr",
        cell: (r) => (
          <span className="text-body font-medium tabular-nums text-text">#{r.index}</span>
        ),
      },
      {
        id: "due",
        header: "Due date",
        width: "1fr",
        cell: (r) => (
          <span className="text-body tabular-nums text-text-subtle">{fmtDate(r.dueDate)}</span>
        ),
      },
      {
        id: "amount",
        header: "Amount",
        width: "0.9fr",
        className: "text-right",
        cell: (r) => (
          <span className="text-body font-medium tabular-nums text-text">{fmtMoney(r.amount)}</span>
        ),
      },
      {
        id: "paidOn",
        header: "Paid on",
        width: "1.2fr",
        cell: (r) =>
          r.paidOn ? (
            <span className="text-body tabular-nums text-text-subtle">
              {fmtDate(r.paidOn)}
              {r.paidAmount && r.paidAmount !== r.amount ? (
                <span className="ml-050 text-body-small text-text-warning">
                  · {fmtMoney(r.paidAmount)}
                </span>
              ) : null}
            </span>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
      },
      {
        id: "status",
        header: "Status",
        width: "0.8fr",
        cell: (r) => {
          const t = STATUS_META[r.status];
          return <StatusChip label={t.label} tone={t.tone} />;
        },
      },
      {
        id: "balance",
        header: "Balance carried",
        width: "1fr",
        className: "text-right",
        cell: (r) => (
          <span className="text-body tabular-nums text-text-subtle">
            {fmtMoney(r.balanceCarried)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-200">
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
          <div
            className="h-full rounded-full bg-background-brand-bold"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="rounded-large border border-border bg-surface p-200">
        <div className="mb-150 text-body-small font-semibold text-text-subtle">
          Installment timeline
        </div>
        <div className="flex items-center gap-050 overflow-x-auto pb-050">
          {customer.emi.map((e) => {
            const t = STATUS_META[e.status];
            return (
              <div
                key={e.id}
                className="flex min-w-[3.25rem] flex-1 flex-col items-center gap-050"
                title={`EMI #${e.index} · ${fmtDate(e.dueDate)}`}
              >
                <div className={cn("h-100 w-full rounded-full", t.dot)} />
                <div className="text-body-small tabular-nums text-text-subtlest">#{e.index}</div>
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

      <FilterTable
        rows={customer.emi}
        getRowId={(r) => r.id}
        getStatus={(r) => r.status}
        chips={chips}
        columns={columns}
        emptyMessage="No installments on this account."
        ariaLabel="EMI schedule"
      />
    </div>
  );
}
