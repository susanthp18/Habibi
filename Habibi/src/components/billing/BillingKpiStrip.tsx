import { ArrowDown, ArrowUp, TrendingUp, Wallet, Coins, Gauge } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import type { DayPoint } from "@/data/billing-seed";
import { inrCompact } from "@/data/billing-seed";
import { cn } from "@/lib/utils";

function DeltaChip({ pct }: { pct: number }) {
  const up = pct >= 0;
  const bad = up; // higher spend = worse
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10.5px] font-semibold",
        bad ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700",
      )}
    >
      {up ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

export function BillingKpiStrip({
  daily,
  spendMtd,
  spendPrev,
  costPerCall,
  costPerCallPrev,
  forecast,
  budgetCap,
}: {
  daily: DayPoint[];
  spendMtd: number;
  spendPrev: number;
  costPerCall: number;
  costPerCallPrev: number;
  forecast: number;
  budgetCap: number;
}) {
  const spendDelta = spendPrev > 0 ? ((spendMtd - spendPrev) / spendPrev) * 100 : 0;
  const cpcDelta = costPerCallPrev > 0 ? ((costPerCall - costPerCallPrev) / costPerCallPrev) * 100 : 0;
  const budgetPct = budgetCap > 0 ? Math.round((spendMtd / budgetCap) * 100) : 0;
  const forecastPct = budgetCap > 0 ? Math.round((forecast / budgetCap) * 100) : 0;

  const spark = daily.map((d) => ({
    v: Object.values(d.values).reduce((a, b) => a + b, 0),
  }));

  const budgetTone =
    budgetPct < 70 ? "text-emerald-600" : budgetPct < 90 ? "text-amber-600" : "text-rose-600";
  const forecastTone =
    forecastPct < 100 ? "text-emerald-600" : forecastPct < 115 ? "text-amber-600" : "text-rose-600";

  return (
    <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-[var(--border-token)] bg-surface-app px-6 py-3 lg:grid-cols-4">
      {/* Spend MTD */}
      <div className="relative overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Spend · this period</span>
          <Wallet className="h-4 w-4 text-brand-primary" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-[22px] font-semibold text-brand-navy">{inrCompact(spendMtd)}</span>
          <DeltaChip pct={spendDelta} />
        </div>
        <div className="mt-2 h-8">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={spark} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="sparkSpend" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--brand-primary)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--brand-primary)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="v" stroke="var(--brand-primary)" strokeWidth={1.5} fill="url(#sparkSpend)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 text-[10.5px] text-text-muted">vs prior period {inrCompact(spendPrev)}</div>
      </div>

      {/* Cost / resolved call */}
      <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Cost / resolved call</span>
          <Coins className="h-4 w-4 text-amber-500" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-[22px] font-semibold text-brand-navy">₹{costPerCall.toFixed(1)}</span>
          <DeltaChip pct={cpcDelta} />
        </div>
        <div className="mt-6 text-[10.5px] text-text-muted">
          Hero unit-economics metric — lower is better.
        </div>
      </div>

      {/* Forecast EOM */}
      <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Forecast · end of month</span>
          <TrendingUp className={cn("h-4 w-4", forecastTone)} />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={cn("text-[22px] font-semibold", forecastTone)}>{inrCompact(forecast)}</span>
          <span className="text-[11px] text-text-muted">of {inrCompact(budgetCap)}</span>
        </div>
        <div className="mt-6 text-[10.5px] text-text-muted">
          {forecastPct}% of monthly cap at current daily burn.
        </div>
      </div>

      {/* Budget usage */}
      <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Budget usage · MTD</span>
          <Gauge className={cn("h-4 w-4", budgetTone)} />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={cn("text-[22px] font-semibold", budgetTone)}>{budgetPct}%</span>
        </div>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              budgetPct < 70 && "bg-emerald-500",
              budgetPct >= 70 && budgetPct < 90 && "bg-amber-500",
              budgetPct >= 90 && "bg-rose-500",
            )}
            style={{ width: `${Math.min(100, budgetPct)}%` }}
          />
        </div>
        <div className="mt-2 text-[10.5px] text-text-muted">
          {inrCompact(spendMtd)} / {inrCompact(budgetCap)}
        </div>
      </div>
    </div>
  );
}
