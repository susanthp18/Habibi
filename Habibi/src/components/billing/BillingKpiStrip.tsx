import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, TrendingUp, Wallet, Coins, Gauge } from "lucide-react";
import type { DayPoint } from "@/data/billing-seed";
import { inrCompact } from "@/data/billing-seed";
import { LivelineSpark } from "@/components/charts";
import { cn } from "@/lib/utils";

function DeltaChip({ pct }: { pct: number }) {
  const up = pct >= 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-025 rounded px-075 py-025 text-body-small font-semibold",
        up ? "bg-background-danger-subtler text-text-danger-bolder" : "bg-background-success-subtler text-text-success-bolder",
      )}
    >
      {up ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function KpiCard({
  label,
  icon,
  children,
  footer,
}: {
  label: string;
  icon: ReactNode;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="flex min-h-[8.25rem] flex-col rounded-large border border-border bg-surface p-200 shadow-raised">
      <div className="flex items-center justify-between">
        <span className="text-body-small font-medium text-text-subtlest">{label}</span>
        {icon}
      </div>
      <div className="mt-050">{children}</div>
      <div className="mt-auto min-h-[2.25rem] pt-100 text-body-small text-text-subtlest">{footer}</div>
    </div>
  );
}

export function BillingKpiStrip({
  daily,
  spendMtd,
  spendPrev,
  costPerCall,
  costPerCallPrev,
  attributedCostPerCall,
  attributedCalls,
  forecast,
  budgetCap,
}: {
  daily: DayPoint[];
  spendMtd: number;
  spendPrev: number;
  costPerCall: number;
  costPerCallPrev: number;
  /** Mean over calls carrying attributed usage. 0 when none are metered yet. */
  attributedCostPerCall: number;
  attributedCalls: number;
  forecast: number;
  budgetCap: number;
}) {
  const spendDelta = spendPrev > 0 ? ((spendMtd - spendPrev) / spendPrev) * 100 : 0;
  const cpcDelta = costPerCallPrev > 0 ? ((costPerCall - costPerCallPrev) / costPerCallPrev) * 100 : 0;
  // Only claim a measured unit cost when calls were actually metered; a window
  // that predates metering has attributedCalls === 0, which is not a real ₹0.
  const measured = attributedCalls > 0;
  const budgetPct = budgetCap > 0 ? Math.round((spendMtd / budgetCap) * 100) : 0;
  const forecastPct = budgetCap > 0 ? Math.round((forecast / budgetCap) * 100) : 0;

  const spark = daily.map((d) => Object.values(d.values).reduce((a, b) => a + b, 0));

  const budgetTone =
    budgetPct < 70 ? "text-text-success" : budgetPct < 90 ? "text-text-warning" : "text-text-danger";
  const forecastTone =
    forecastPct < 100 ? "text-text-success" : forecastPct < 115 ? "text-text-warning" : "text-text-danger";

  return (
    <div className="grid grid-cols-2 gap-150 md:grid-cols-4">
      <KpiCard
        label="Spend · this period"
        icon={<Wallet className="h-4 w-4 text-text-brand" />}
        footer={<span>vs prior {inrCompact(spendPrev)}</span>}
      >
        <div className="flex items-baseline gap-100">
          <span className="text-[1.5rem] font-semibold text-text">{inrCompact(spendMtd)}</span>
          <DeltaChip pct={spendDelta} />
        </div>
        <div className="mt-050 overflow-hidden rounded-medium bg-surface-sunken">
          <LivelineSpark data={spark} color="#1868db" height={28} />
        </div>
      </KpiCard>

      {/* Two different numbers wear this label. `attributedCostPerCall` is
          measured — the mean of usage actually billed to individual calls.
          `costPerCall` is allocated: all spend (including embeddings and batch
          work no call incurred) divided by the resolved-call count. Prefer the
          measured one, and never present the allocated one as if it were it. */}
      <KpiCard
        label={measured ? "Cost / call · measured" : "Cost / resolved call"}
        icon={<Coins className="h-4 w-4 text-text-brand" />}
        footer={
          measured ? (
            <span>
              Metered across {attributedCalls.toLocaleString("en-IN")} call
              {attributedCalls === 1 ? "" : "s"} · allocated ₹{costPerCall.toFixed(2)}
            </span>
          ) : (
            <span>Allocated — total spend ÷ resolved calls</span>
          )
        }
      >
        <div className="flex items-baseline gap-100">
          <span className="text-[1.5rem] font-semibold text-text">
            ₹{(measured ? attributedCostPerCall : costPerCall).toFixed(2)}
          </span>
          {!measured && <DeltaChip pct={cpcDelta} />}
        </div>
      </KpiCard>

      <KpiCard
        label="Forecast · end of month"
        icon={<TrendingUp className={cn("h-4 w-4", forecastTone)} />}
        footer={
          <span>
            {forecastPct}% of cap at current burn · cap {inrCompact(budgetCap)}
          </span>
        }
      >
        <div className="flex items-baseline gap-100">
          <span className={cn("text-[1.5rem] font-semibold", forecastTone)}>{inrCompact(forecast)}</span>
        </div>
      </KpiCard>

      <KpiCard
        label="Budget usage"
        icon={<Gauge className={cn("h-4 w-4", budgetTone)} />}
        footer={
          <span>
            {inrCompact(spendMtd)} / {inrCompact(budgetCap)}
          </span>
        }
      >
        <div className="flex items-baseline gap-100">
          <span className={cn("text-[1.5rem] font-semibold", budgetTone)}>{budgetPct}%</span>
        </div>
        <div className="mt-100 h-100 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              budgetPct < 70 && "bg-background-success-bold",
              budgetPct >= 70 && budgetPct < 90 && "bg-background-warning-bold",
              budgetPct >= 90 && "bg-background-danger-bold",
            )}
            style={{ width: `${Math.min(100, budgetPct)}%` }}
          />
        </div>
      </KpiCard>
    </div>
  );
}
