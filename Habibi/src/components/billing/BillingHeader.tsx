import { Download, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Env, Period, Tenant } from "@/data/billing-seed";
import { Lozenge } from "@/components/ui/lozenge";

const PERIODS: Array<{ key: Period; label: string }> = [
  { key: "mtd", label: "MTD" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "quarter", label: "90d" },
];

export function BillingHeader({
  period,
  onPeriod,
  tenantId,
  onTenant,
  tenants,
  env,
  onEnv,
  onExportCsv,
  refreshing,
}: {
  period: Period;
  onPeriod: (p: Period) => void;
  tenantId: string;
  onTenant: (id: string) => void;
  tenants: Tenant[];
  env: Env;
  onEnv: (e: Env) => void;
  onExportCsv: () => void;
  refreshing?: boolean;
}) {
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <h1 className="heading-medium font-semibold text-text">Billing & usage</h1>
        <Lozenge tone="neutral">Live Azure meters only</Lozenge>
        <div className="ml-auto flex flex-wrap items-center gap-100">
          {refreshing && (
            <RefreshCw
              className="h-3.5 w-3.5 animate-spin text-text-subtlest"
              aria-label="Refreshing"
            />
          )}
          <div className="inline-flex overflow-hidden rounded-medium border border-border">
            {(["production", "sandbox"] as Env[]).map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => onEnv(e)}
                className={cn(
                  "px-150 py-050 text-body-small capitalize",
                  env === e
                    ? "bg-background-brand-subtlest font-semibold text-text-brand"
                    : "text-text-subtle hover:bg-surface-sunken",
                )}
              >
                {e === "production" ? "Prod" : "Sandbox"}
              </button>
            ))}
          </div>
          <div className="inline-flex overflow-hidden rounded-medium border border-border">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => onPeriod(p.key)}
                className={cn(
                  "px-150 py-050 text-body-small",
                  period === p.key
                    ? "bg-background-brand-subtlest font-semibold text-text-brand"
                    : "text-text-subtle hover:bg-surface-sunken",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <select
            value={tenantId}
            onChange={(e) => onTenant(e.target.value)}
            aria-label="Filter billing by tenant"
            className="max-w-[12.5rem] rounded-medium border border-border bg-surface px-100 py-050 text-body-small"
          >
            <option value="all">All tenants</option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onExportCsv}
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest"
          >
            <Download className="h-3.5 w-3.5" /> Export CSV
          </button>
        </div>
      </div>
      <p className="mt-050 text-body-small text-text-subtle">
        Spend is rolled up from live Azure OpenAI + Speech usage events (tokens / minutes /
        characters × list price × FX).
      </p>
    </header>
  );
}
