import { useMemo } from "react";
import { User, Wallet } from "lucide-react";
import { fmtDate, fmtMoney, type PaymentPlan } from "@/data/promises-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

interface Props {
  plans: PaymentPlan[];
  onOpen: (p: PaymentPlan) => void;
}

const statusChip: Record<PaymentPlan["status"], LozengeTone> = {
  on_track: "success",
  slipped: "warning",
  completed: "selected",
};

const statusRank: Record<PaymentPlan["status"], number> = {
  slipped: 3,
  on_track: 2,
  completed: 1,
};

export function PaymentPlansTable({ plans, onOpen }: Props) {
  const columns = useMemo<RecordsColumn<PaymentPlan>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        headerIcon: <User className="h-3.5 w-3.5" />,
        sticky: true,
        sortable: true,
        sortValue: (p) => p.customerName,
        className: "min-w-[12rem]",
        cell: (p) => (
          <button type="button" onClick={() => onOpen(p)} className="flex min-w-0 items-center gap-100 text-left">
            <RecordsAvatarMark label={p.customerName || "?"} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-text-brand hover:underline">
                {p.customerName}
              </span>
              <span className="block truncate text-body-small text-text-subtlest">
                #{p.accountTail} · {p.id}
              </span>
            </span>
          </button>
        ),
        footer: (visible) => (
          <span>
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">plans</span>
          </span>
        ),
      },
      {
        id: "total",
        header: "Total",
        headerIcon: <Wallet className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (p) => p.total ?? 0,
        align: "right",
        cell: (p) => <span className="tabular-nums font-semibold text-text">{fmtMoney(p.total)}</span>,
        footer: (visible) => {
          const sum = visible.reduce((s, p) => s + (Number(p.total) || 0), 0);
          return <span className="font-semibold tabular text-text">{fmtMoney(sum)}</span>;
        },
      },
      {
        id: "installments",
        header: "Installments",
        sortable: true,
        sortValue: (p) => {
          const paid = (p.installments ?? []).filter((i) => i.paid).length;
          const n = p.installments?.length || 1;
          return paid / n;
        },
        cell: (p) => {
          const paid = (p.installments ?? []).filter((i) => i.paid).length;
          const n = p.installments?.length || 0;
          const pct = n ? Math.round((paid / n) * 100) : 0;
          return (
            <div className="flex items-center gap-100">
              <div className="tabular-nums text-text-subtle">
                {paid}/{n}
              </div>
              <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                <div className="h-full bg-background-brand-bold" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        },
      },
      {
        id: "cadence",
        header: "Cadence",
        sortable: true,
        sortValue: (p) => p.cadence,
        cell: (p) => <RecordsTag name={(p.cadence || "—").replace(/^./, (c) => c.toUpperCase())} />,
      },
      {
        id: "nextDue",
        header: "Next due",
        sortable: true,
        sortValue: (p) => {
          const next = (p.installments ?? []).find((i) => !i.paid);
          return next?.dueDate ? new Date(next.dueDate).getTime() : Number.MAX_SAFE_INTEGER;
        },
        cell: (p) => {
          const next = (p.installments ?? []).find((i) => !i.paid);
          return next ? (
            <span className="text-text-subtle">{fmtDate(next.dueDate)}</span>
          ) : (
            <span className="text-text-subtlest">—</span>
          );
        },
      },
      {
        id: "status",
        header: "Status",
        sortable: true,
        sortValue: (p) => statusRank[p.status] ?? 0,
        cell: (p) => (
          <Lozenge tone={statusChip[p.status] ?? "neutral"} className="capitalize">
            {(p.status || "—").replace("_", " ")}
          </Lozenge>
        ),
        footer: (visible) => {
          const slipped = visible.filter((p) => p.status === "slipped").length;
          return <span className="text-text-subtlest">{slipped} slipped</span>;
        },
      },
      {
        id: "owner",
        header: "Owner",
        sortable: true,
        sortValue: (p) => p.owner || "",
        cell: (p) => <span className="text-text-subtle">{p.owner || "—"}</span>,
      },
    ],
    [onOpen],
  );

  return (
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between gap-150 border-b border-border px-200 py-150">
        <div>
          <div className="text-body font-semibold text-text">Payment plans</div>
          <div className="mt-025 text-body-small text-text-subtlest">
            {plans.length} plan{plans.length === 1 ? "" : "s"} · {plans.filter((p) => p.status === "on_track").length}{" "}
            on-track · {plans.filter((p) => p.status === "slipped").length} slipped
          </div>
        </div>
      </div>
      <div className="p-100">
        <RecordsTable
          rows={plans}
          getRowId={(p) => p.id}
          columns={columns}
          emptyMessage='No payment plans yet. Use "+ Payment plan" to build one.'
          ariaLabel="Payment plans table"
          defaultSort={{ id: "status", dir: -1 }}
        />
      </div>
    </div>
  );
}
