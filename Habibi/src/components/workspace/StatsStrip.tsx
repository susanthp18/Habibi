import { ArrowDownRight, ArrowUpRight, PhoneCall, Clock, CheckCircle2, HandCoins } from "lucide-react";
import { stats } from "@/data/workspace-seed";

const tiles = [
  {
    label: "Calls handled",
    value: stats.callsHandled.toString(),
    delta: stats.callsHandledDelta,
    trend: "up" as const,
    icon: PhoneCall,
  },
  {
    label: "Avg handle time",
    value: stats.aht,
    delta: stats.ahtDelta,
    trend: "down-good" as const,
    icon: Clock,
  },
  {
    label: "Resolutions",
    value: `${stats.resolutions}`,
    delta: `${stats.resolutionRate} rate`,
    trend: "up" as const,
    icon: CheckCircle2,
  },
  {
    label: "Promises captured",
    value: stats.promisesCount.toString(),
    delta: `₹${stats.promisesAmount.toLocaleString("en-IN")}`,
    trend: "up" as const,
    icon: HandCoins,
  },
];

export function StatsStrip() {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {tiles.map((t, i) => {
        const Icon = t.icon;
        const good = t.trend === "up" || t.trend === "down-good";
        const Arrow = t.trend === "down-good" ? ArrowDownRight : ArrowUpRight;
        return (
          <div
            key={t.label}
            className="animate-fade-up rounded-[10px] border border-[var(--border-token)] bg-surface-card p-5 shadow-card"
            style={{ animationDelay: `${i * 30}ms` }}
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
                {t.label}
              </span>
              <Icon className="h-4 w-4 text-text-muted" />
            </div>
            <div className="mt-2 font-mono text-[32px] font-bold leading-none text-brand-navy tabular">
              {t.value}
            </div>
            <div
              className={`mt-2 inline-flex items-center gap-1 text-[12px] ${
                good ? "text-success" : "text-danger"
              }`}
            >
              <Arrow className="h-3.5 w-3.5" />
              <span>{t.delta}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
