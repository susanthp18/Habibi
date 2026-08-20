import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Building2,
  CalendarClock,
  ChevronRight,
  CreditCard,
  Hash,
  Search,
  ShieldAlert,
  Timer,
  Wallet,
} from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { RiskBadge } from "@/components/customer360/RiskBadge";
import { Input } from "@/components/ui/input";
import { fmtMoney, fmtRelative, type Customer } from "@/data/customer360-seed";
import { useCustomers } from "@/api/customers";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

export const Route = createFileRoute("/customers/")({
  head: () => ({
    meta: [
      { title: "Customers — Customer 360" },
      { name: "description", content: "Search and open the unified master record for every debtor." },
      { property: "og:title", content: "Customer 360 — BigBound AI" },
      { property: "og:description", content: "Unified ledger, EMI schedule, interactions, promises, disputes, and documents." },
    ],
  }),
  component: CustomersIndex,
});

/** Matches backend seed / demo actor used across CRM screens. */
const ASSIGNED_TO_ME = "Priya Nair";

const RISK_RANK: Record<Customer["risk"], number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

function CustomersIndex() {
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"all" | "mine" | "risk">("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data: customers = [], isPending, isError, error } = useCustomers();

  const rows = useMemo(() => {
    let out = customers;
    if (tab === "mine") out = out.filter((c) => c.assignedTo === ASSIGNED_TO_ME);
    if (tab === "risk") out = out.filter((c) => c.risk === "critical" || c.risk === "high");
    if (q.trim()) {
      const s = q.toLowerCase();
      out = out.filter(
        (c) =>
          c.name.toLowerCase().includes(s) ||
          c.accountId.toLowerCase().includes(s) ||
          (c.account?.product ?? "").toLowerCase().includes(s),
      );
    }
    return out;
  }, [customers, q, tab]);

  const columns = useMemo<RecordsColumn<Customer>[]>(
    () => [
      {
        id: "name",
        header: "Customer",
        headerIcon: <Building2 className="h-3.5 w-3.5" />,
        sticky: true,
        sortable: true,
        sortValue: (c) => c.name,
        className: "min-w-[16rem]",
        cell: (c) => (
          <Link
            to="/customers/$customerId"
            params={{ customerId: c.id }}
            className="flex min-w-0 items-center gap-100"
          >
            <RecordsAvatarMark label={c.name} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-text-brand hover:underline">
                {c.name}
              </span>
              <span className="block truncate text-body-small text-text-subtlest">
                Assigned · {c.assignedTo || "—"}
              </span>
            </span>
          </Link>
        ),
        footer: (visible) => (
          <span>
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">count</span>
          </span>
        ),
      },
      {
        id: "account",
        header: "Account",
        headerIcon: <Hash className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.accountId,
        cell: (c) => <span className="font-mono text-xs text-text-subtle tabular">{c.accountId}</span>,
      },
      {
        id: "product",
        header: "Product",
        headerIcon: <CreditCard className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.account?.product ?? "",
        cell: (c) =>
          c.account?.product ? <RecordsTag name={c.account.product} /> : <span className="text-text-subtlest">—</span>,
      },
      {
        id: "outstanding",
        header: "Outstanding",
        headerIcon: <Wallet className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.outstanding ?? 0,
        align: "right",
        cell: (c) => (
          <span className="text-sm font-semibold tabular text-text">{fmtMoney(c.outstanding)}</span>
        ),
        footer: (visible) => {
          const total = visible.reduce((sum, c) => sum + (Number(c.outstanding) || 0), 0);
          return <span className="font-semibold tabular text-text">{fmtMoney(total)} total</span>;
        },
      },
      {
        id: "dpd",
        header: "DPD",
        headerIcon: <Timer className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.account?.dpd ?? 0,
        align: "right",
        cell: (c) => {
          const dpd = c.account?.dpd ?? 0;
          return (
            <span
              className={cn(
                "text-xs tabular",
                dpd > 60 ? "font-semibold text-text-danger" : dpd > 30 ? "text-text-warning" : "text-text-subtle",
              )}
            >
              {dpd}d
            </span>
          );
        },
        footer: (visible) => {
          if (!visible.length) return <span className="text-text-subtlest">—</span>;
          const avg = Math.round(
            visible.reduce((sum, c) => sum + (c.account?.dpd ?? 0), 0) / visible.length,
          );
          return <span className="tabular">{avg}d avg</span>;
        },
      },
      {
        id: "risk",
        header: "Risk",
        headerIcon: <ShieldAlert className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => RISK_RANK[c.risk] ?? 0,
        align: "center",
        cell: (c) => <RiskBadge level={c.risk} />,
        footer: (visible) => {
          const hot = visible.filter((c) => c.risk === "critical" || c.risk === "high").length;
          return (
            <span className="inline-flex items-center gap-050">
              <span className="h-150 w-150 rounded-full bg-icon-danger" aria-hidden />
              {hot} at-risk
            </span>
          );
        },
      },
      {
        id: "lastContact",
        header: "Last contact",
        headerIcon: <CalendarClock className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => (c.lastContact ? new Date(c.lastContact).getTime() : 0),
        cell: (c) => (
          <span className={cn("text-xs tabular text-text-subtle", !c.lastContact && "text-text-subtlest")}>
            {c.lastContact ? fmtRelative(c.lastContact) : "No contact"}
          </span>
        ),
      },
      {
        id: "open",
        header: "Open",
        align: "right",
        cell: (c) => (
          <Link
            to="/customers/$customerId"
            params={{ customerId: c.id }}
            className="inline-flex items-center gap-025 text-xs font-medium text-text-brand hover:underline"
          >
            Open <ChevronRight className="h-3 w-3" />
          </Link>
        ),
        footer: () => (
          <span className="text-text-subtlest">
            {selected.size > 0 ? `${selected.size} selected` : "—"}
          </span>
        ),
      },
    ],
    [selected.size],
  );

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-150 border-b border-border bg-surface px-300 py-200">
          <div>
            <h1 className="text-[1.25rem] font-semibold text-text">Customer 360</h1>
            <p className="text-xs text-text-subtle">Unified master record for every debtor.</p>
          </div>
          <div className="ml-auto flex flex-1 items-center gap-100 md:max-w-md">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search name, account #, or product"
                className="pl-400"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-050 border-b border-border bg-surface px-300">
          {(["all", "mine", "risk"] as const).map((k) => {
            const label = k === "all" ? "All customers" : k === "mine" ? "Assigned to me" : "At-risk";
            const count =
              k === "all"
                ? customers.length
                : k === "mine"
                  ? customers.filter((c) => c.assignedTo === ASSIGNED_TO_ME).length
                  : customers.filter((c) => c.risk === "critical" || c.risk === "high").length;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setTab(k)}
                className={cn(
                  "border-b-2 px-150 py-150 text-sm font-medium",
                  tab === k ? "border-border-brand text-text-brand" : "border-transparent text-text-subtle hover:text-text",
                )}
              >
                {label}
                <Lozenge tone="neutral" className="ml-075">
                  {count}
                </Lozenge>
              </button>
            );
          })}
        </div>

        <div className="min-h-0 flex-1 overflow-hidden p-300">
          {isError ? (
            <div className="rounded-large border border-border-danger bg-background-danger-subtlest px-300 py-200 text-sm text-text-danger">
              Could not load customers from the API.
              {error instanceof Error ? ` ${error.message}` : ""}
            </div>
          ) : (
            <RecordsTable
              rows={rows}
              getRowId={(c) => c.id}
              columns={columns}
              selectable
              selected={selected}
              onSelectedChange={setSelected}
              isLoading={isPending}
              emptyMessage="No customers match your search."
              ariaLabel="Customers table"
              defaultSort={{ id: "name", dir: 1 }}
              className="h-full"
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
