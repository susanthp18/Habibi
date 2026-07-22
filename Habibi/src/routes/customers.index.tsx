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

export const Route = createFileRoute("/customers/")({
  head: () => ({
    meta: [
      { title: "Customers — Customer 360" },
      { name: "description", content: "Search and open the unified master record for every debtor." },
      { property: "og:title", content: "Customer 360 — Collections Agent" },
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
        <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface-card px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-brand-navy">Customer 360</h1>
            <p className="text-xs text-text-secondary">Unified master record for every debtor.</p>
          </div>
          <div className="ml-auto flex flex-1 items-center gap-2 md:max-w-md">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search name or account #"
                className="pl-8"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 border-b border-border bg-surface-card px-6">
          {(["all", "mine", "risk"] as const).map((k) => {
            const label = k === "all" ? "All customers" : k === "mine" ? "Assigned to me" : "At-risk";
            const count = k === "all" ? customers.length : k === "mine" ? customers.filter((c) => c.assignedTo === "Priya Nair").length : customers.filter((c) => c.risk === "critical" || c.risk === "high").length;
            return (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={cn(
                  "border-b-2 px-3 py-2.5 text-sm font-medium",
                  tab === k ? "border-brand-primary text-brand-primary" : "border-transparent text-text-secondary hover:text-brand-navy",
                )}
              >
                {label}
                <span className="ml-1.5 rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] text-text-secondary">{count}</span>
              </button>
            );
          })}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1400px] p-6">
            <div className="overflow-hidden rounded-lg border border-border bg-surface-card shadow-card">
              <table className="w-full text-sm">
                <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-secondary">
                  <tr>
                    <th className="px-4 py-2.5 text-left font-medium">Customer</th>
                    <th className="px-4 py-2.5 text-left font-medium">Account</th>
                    <th className="px-4 py-2.5 text-left font-medium">Product</th>
                    <th className="px-4 py-2.5 text-right font-medium">Outstanding</th>
                    <th className="px-4 py-2.5 text-right font-medium">DPD</th>
                    <th className="px-4 py-2.5 text-center font-medium">Risk</th>
                    <th className="px-4 py-2.5 text-left font-medium">Last contact</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {isPending &&
                    Array.from({ length: 6 }).map((_, i) => (
                      <tr key={`sk-${i}`} className="border-t border-border">
                        <td colSpan={8} className="px-4 py-3">
                          <Skeleton className="h-8 w-full rounded-md" />
                        </td>
                      </tr>
                    ))}
                  {!isPending &&
                    rows.map((c) => (
                    <tr key={c.id} className="border-t border-border hover:bg-brand-tint/40">
                      <td className="px-4 py-3">
                        <Link to="/customers/$customerId" params={{ customerId: c.id }} className="flex items-center gap-2">
                          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-tint text-xs font-semibold text-brand-primary-dark">
                            {c.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-text-primary">{c.name}</div>
                            <div className="text-[10px] text-text-muted">Assigned · {c.assignedTo}</div>
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-xs text-text-secondary tabular">{c.accountId}</td>
                      <td className="px-4 py-3 text-xs text-text-secondary">{c.account.product}</td>
                      <td className="px-4 py-3 text-right text-sm font-semibold text-brand-navy tabular">{fmtMoney(c.outstanding)}</td>
                      <td className="px-4 py-3 text-right text-xs tabular">
                        <span className={c.account.dpd > 60 ? "text-danger" : c.account.dpd > 30 ? "text-warning" : "text-text-secondary"}>
                          {c.account.dpd}d
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <RiskBadge level={c.risk} />
                      </td>
                      <td className="px-4 py-3 text-xs text-text-secondary tabular">{fmtRelative(c.lastContact)}</td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          to="/customers/$customerId"
                          params={{ customerId: c.id }}
                          className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-primary hover:underline"
                        >
                          Open <ChevronRight className="h-3 w-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {!isPending && rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-10 text-center text-sm text-text-muted">
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
