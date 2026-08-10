import { AlertTriangle, ChevronRight } from "lucide-react";
import type { AtRiskAccount } from "@/data/dashboard-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const riskTone: Record<AtRiskAccount["risk"], LozengeTone> = {
  critical: "danger",
  high: "warning",
  medium: "selected",
};

// `accounts.outstanding` is INR. Rendering it with a dollar sign understated
// every exposure on this list by roughly a factor of 85 to anyone reading it.
function fmtMoney(n: number) {
  return `₹${n.toLocaleString("en-IN")}`;
}

export function AtRiskAccounts({ accounts, onOpen }: { accounts: AtRiskAccount[]; onOpen?: (a: AtRiskAccount) => void }) {
  return (
    <div className="flex h-full flex-col rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-200 py-150">
        <div>
          <h3 className="text-sm font-semibold text-text">At-risk accounts</h3>
          <p className="text-xs text-text-subtle">Highest exposure — needs supervisor attention</p>
        </div>
        <AlertTriangle className="h-4 w-4 text-text-danger" />
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        {accounts.map((a) => (
          <li key={a.id}>
            <button
              onClick={() => onOpen?.(a)}
              className="flex w-full items-center gap-150 px-200 py-150 text-left transition-colors hover:bg-background-brand-subtlest/40"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-background-brand-subtlest text-xs font-semibold text-text-brand">
                {a.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-100">
                  <span className="truncate text-sm font-medium text-text">{a.name}</span>
                  <Lozenge tone={riskTone[a.risk]} className="shrink-0">
                    {a.risk}
                  </Lozenge>
                </div>
                <div className="mt-025 flex items-center gap-100 text-body-small text-text-subtle">
                  <span className="tabular">{a.account}</span>
                  <span>·</span>
                  <span>{a.product}</span>
                  <span>·</span>
                  <span className="tabular">{a.daysPastDue}d past due</span>
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-sm font-semibold text-text tabular">{fmtMoney(a.outstanding)}</div>
                <div className="text-body-small text-text-subtlest">Last: {a.lastContact}</div>
              </div>
              <ChevronRight className="h-4 w-4 shrink-0 text-text-subtlest" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
