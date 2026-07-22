import { AlertTriangle, ChevronRight } from "lucide-react";
import type { AtRiskAccount } from "@/data/dashboard-seed";
import { cn } from "@/lib/utils";

const riskStyle: Record<AtRiskAccount["risk"], string> = {
  critical: "bg-danger-bg text-danger",
  high: "bg-warning-bg text-warning",
  medium: "bg-brand-tint text-brand-primary-dark",
};

function fmtMoney(n: number) {
  return `$${n.toLocaleString()}`;
}

export function AtRiskAccounts({ accounts, onOpen }: { accounts: AtRiskAccount[]; onOpen?: (a: AtRiskAccount) => void }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface-card shadow-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-brand-navy">At-risk accounts</h3>
          <p className="text-xs text-text-secondary">Highest exposure — needs supervisor attention</p>
        </div>
        <AlertTriangle className="h-4 w-4 text-danger" />
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        {accounts.map((a) => (
          <li key={a.id}>
            <button
              onClick={() => onOpen?.(a)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-brand-tint/40"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-tint text-xs font-semibold text-brand-primary-dark">
                {a.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-text-primary">{a.name}</span>
                  <span className={cn("shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide", riskStyle[a.risk])}>
                    {a.risk}
                  </span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-secondary">
                  <span className="tabular">{a.account}</span>
                  <span>·</span>
                  <span>{a.product}</span>
                  <span>·</span>
                  <span className="tabular">{a.daysPastDue}d past due</span>
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-sm font-semibold text-brand-navy tabular">{fmtMoney(a.outstanding)}</div>
                <div className="text-[10px] text-text-muted">Last: {a.lastContact}</div>
              </div>
              <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
