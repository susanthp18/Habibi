import { ArrowDown, ArrowUp, TrendingUp, Wallet, Coins, Gauge } from "lucide-react";
import type { DayPoint } from "@/api/types/billing";
import { inrCompact } from "@/lib/format";
import { LivelineSpark } from "@/components/charts";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import type { StatTone } from "@/components/ui/stat-tile";
import { cn } from "@/lib/utils";

function DeltaChip({ pct }: { pct: number }) {
  const up = pct >= 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-025 rounded px-075 py-025 text-body-small font-semibold",
        up
          ? "bg-background-danger-subtler text-text-danger-bolder"
          : "bg-background-success-subtler text-text-success-bolder",
      )}
    >
      {up ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

const BAR: Record<StatTone, string> = {
  success: "bg-background-success-bold",
  warning: "bg-background-warning-bold",
  danger: "bg-background-danger-bold",
  brand: "bg-background-brand-bold",
  info: "bg-background-brand-bold",
  discovery: "bg-background-brand-bold",
  neutral: "bg-background-brand-bold",
};

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
  const cpcDelta =
    costPerCallPrev > 0 ? ((costPerCall - costPerCallPrev) / costPerCallPrev) * 100 : 0;
  // Only claim a measured unit cost when calls were actually metered; a window
  // that predates metering has attributedCalls === 0, which is not a real ₹0.
  const measured = attributedCalls > 0;
  const budgetPct = budgetCap > 0 ? Math.round((spendMtd / budgetCap) * 100) : 0;
  const forecastPct = budgetCap > 0 ? Math.round((forecast / budgetCap) * 100) : 0;

  const spark = daily.map((d) => Object.values(d.values).reduce((a, b) => a + b, 0));

  const budgetTone: StatTone = budgetPct < 70 ? "success" : budgetPct < 90 ? "warning" : "danger";
  const forecastTone: StatTone =
    forecastPct < 100 ? "success" : forecastPct < 115 ? "warning" : "danger";

  return (
    <MetricsStrip
      className="gap-150 md:grid-cols-4"
      tiles={[
        {
          variant: "card",
          label: "Spend · this period",
          icon: Wallet,
          value: (
            <span className="flex items-baseline gap-100">
              {inrCompact(spendMtd)}
              <DeltaChip pct={spendDelta} />
            </span>
          ),
          sub: `vs prior ${inrCompact(spendPrev)}`,
          footer: (
            <div className="overflow-hidden rounded-medium bg-surface-sunken">
              <LivelineSpark data={spark} color="#1868db" height={28} />
            </div>
          ),
        },
        // Two different numbers wear this label. `attributedCostPerCall` is
        // measured — the mean of usage actually billed to individual calls.
        // `costPerCall` is allocated: all spend (including embeddings and batch
        // work no call incurred) divided by the resolved-call count. Prefer the
        // measured one, and never present the allocated one as if it were it.
        {
          variant: "card",
          label: measured ? "Cost / call · measured" : "Cost / resolved call",
          icon: Coins,
          value: (
            <span className="flex items-baseline gap-100">
              ₹{(measured ? attributedCostPerCall : costPerCall).toFixed(2)}
              {!measured && <DeltaChip pct={cpcDelta} />}
            </span>
          ),
          sub: measured
            ? `Metered across ${attributedCalls.toLocaleString("en-IN")} call${attributedCalls === 1 ? "" : "s"} · allocated ₹${costPerCall.toFixed(2)}`
            : "Allocated — total spend ÷ resolved calls",
        },
        {
          variant: "card",
          label: "Forecast · end of month",
          icon: TrendingUp,
          value: inrCompact(forecast),
          tone: forecastTone,
          sub: `${forecastPct}% of cap at current burn · cap ${inrCompact(budgetCap)}`,
        },
        {
          variant: "card",
          label: "Budget usage",
          icon: Gauge,
          value: `${budgetPct}%`,
          tone: budgetTone,
          sub: `${inrCompact(spendMtd)} / ${inrCompact(budgetCap)}`,
          footer: (
            <div className="h-100 w-full overflow-hidden rounded-full bg-surface-sunken">
              <div
                className={cn("h-full rounded-full transition-all", BAR[budgetTone])}
                style={{ width: `${Math.min(100, budgetPct)}%` }}
              />
            </div>
          ),
        },
      ]}
    />
  );
}
