import { Download, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Env, Period, Tenant } from "@/data/billing-seed";

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
    <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-[18px] font-semibold text-brand-navy">Billing & Usage</h1>
        <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">
          Live Azure meters only
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {refreshing && (
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-text-muted" aria-label="Refreshing" />
          )}
          <div className="inline-flex overflow-hidden rounded-md border border-[var(--border-token)]">
            {(["production", "sandbox"] as Env[]).map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => onEnv(e)}
                className={cn(
                  "px-2.5 py-1 text-[12px] capitalize",
                  env === e
                    ? "bg-brand-tint font-semibold text-brand-primary-dark"
                    : "text-text-secondary hover:bg-surface-sunken",
                )}
              >
                {e === "production" ? "Prod" : "Sandbox"}
              </button>
            ))}
          </div>
          <div className="inline-flex overflow-hidden rounded-md border border-[var(--border-token)]">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => onPeriod(p.key)}
                className={cn(
                  "px-2.5 py-1 text-[12px]",
                  period === p.key
                    ? "bg-brand-tint font-semibold text-brand-primary-dark"
                    : "text-text-secondary hover:bg-surface-sunken",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <select
            value={tenantId}
            onChange={(e) => onTenant(e.target.value)}
            className="max-w-[200px] rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[12px]"
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
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-brand-primary hover:bg-brand-tint"
          >
            <Download className="h-3.5 w-3.5" /> Export CSV
          </button>
        </div>
      </div>
      <p className="mt-1 text-[12px] text-text-secondary">
        Spend is rolled up from live Azure OpenAI + Speech usage events (tokens / minutes / characters × list price × FX).
      </p>
    </header>
  );
}
