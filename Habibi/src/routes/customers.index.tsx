import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ChevronRight, Search } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { RiskBadge } from "@/components/customer360/RiskBadge";
import { Input } from "@/components/ui/input";
import { fmtMoney, fmtRelative } from "@/data/customer360-seed";
import { useCustomers } from "@/api/customers";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

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

function CustomersIndex() {
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"all" | "mine" | "risk">("all");

  const { data: customers = [], isPending } = useCustomers();

  const rows = useMemo(() => {
    let out = customers;
    if (tab === "mine") out = out.filter((c) => c.assignedTo === "Priya Nair");
    if (tab === "risk") out = out.filter((c) => c.risk === "critical" || c.risk === "high");
    if (q.trim()) {
      const s = q.toLowerCase();
      out = out.filter((c) => c.name.toLowerCase().includes(s) || c.accountId.toLowerCase().includes(s));
    }
    return out;
  }, [customers, q, tab]);

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
                placeholder="Search name or account #"
                className="pl-400"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-050 border-b border-border bg-surface px-300">
          {(["all", "mine", "risk"] as const).map((k) => {
            const label = k === "all" ? "All customers" : k === "mine" ? "Assigned to me" : "At-risk";
            const count = k === "all" ? customers.length : k === "mine" ? customers.filter((c) => c.assignedTo === "Priya Nair").length : customers.filter((c) => c.risk === "critical" || c.risk === "high").length;
            return (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={cn(
                  "border-b-2 px-150 py-150 text-sm font-medium",
                  tab === k ? "border-border-brand text-text-brand" : "border-transparent text-text-subtle hover:text-text",
                )}
              >
                {label}
                <Lozenge tone="neutral" className="ml-075">{count}</Lozenge>
              </button>
            );
          })}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[87.5rem] p-300">
            <div className="overflow-hidden rounded-large border border-border bg-surface">
              <table className="w-full text-sm">
                <thead className="bg-surface-sunken text-body-small text-text-subtle">
                  <tr>
                    <th className="px-200 py-150 text-left font-medium">Customer</th>
                    <th className="px-200 py-150 text-left font-medium">Account</th>
                    <th className="px-200 py-150 text-left font-medium">Product</th>
                    <th className="px-200 py-150 text-right font-medium">Outstanding</th>
                    <th className="px-200 py-150 text-right font-medium">DPD</th>
                    <th className="px-200 py-150 text-center font-medium">Risk</th>
                    <th className="px-200 py-150 text-left font-medium">Last contact</th>
                    <th className="px-200 py-150" />
                  </tr>
                </thead>
                <tbody>
                  {isPending &&
                    Array.from({ length: 6 }).map((_, i) => (
                      <tr key={`sk-${i}`} className="border-t border-border">
                        <td colSpan={8} className="px-200 py-150">
                          <Skeleton className="h-400 w-full rounded-medium" />
                        </td>
                      </tr>
                    ))}
                  {!isPending &&
                    rows.map((c) => (
                    <tr key={c.id} className="border-t border-border hover:bg-background-brand-subtlest/40">
                      <td className="px-200 py-150">
                        <Link to="/customers/$customerId" params={{ customerId: c.id }} className="flex items-center gap-100">
                          <div className="flex h-400 w-400 items-center justify-center rounded-full bg-background-brand-subtlest text-xs font-semibold text-text-brand">
                            {c.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-text">{c.name}</div>
                            <div className="text-body-small text-text-subtlest">Assigned · {c.assignedTo}</div>
                          </div>
                        </Link>
                      </td>
                      <td className="px-200 py-150 text-xs text-text-subtle tabular">{c.accountId}</td>
                      <td className="px-200 py-150 text-xs text-text-subtle">{c.account.product}</td>
                      <td className="px-200 py-150 text-right text-sm font-semibold text-text tabular">{fmtMoney(c.outstanding)}</td>
                      <td className="px-200 py-150 text-right text-xs tabular">
                        <span className={c.account.dpd > 60 ? "text-text-danger" : c.account.dpd > 30 ? "text-text-warning" : "text-text-subtle"}>
                          {c.account.dpd}d
                        </span>
                      </td>
                      <td className="px-200 py-150 text-center">
                        <RiskBadge level={c.risk} />
                      </td>
                      <td className="px-200 py-150 text-xs text-text-subtle tabular">{fmtRelative(c.lastContact)}</td>
                      <td className="px-200 py-150 text-right">
                        <Link
                          to="/customers/$customerId"
                          params={{ customerId: c.id }}
                          className="inline-flex items-center gap-025 text-xs font-medium text-text-brand hover:underline"
                        >
                          Open <ChevronRight className="h-3 w-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {!isPending && rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-200 py-500 text-center text-sm text-text-subtlest">
                        No customers match your search.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
