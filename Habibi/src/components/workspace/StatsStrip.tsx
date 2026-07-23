import { ArrowDownRight, ArrowUpRight, PhoneCall, Clock, CheckCircle2, HandCoins } from "lucide-react";
import { useWorkspaceSummary } from "@/api/workspace";
import { cn } from "@/lib/utils";

/**
 * Rolling 7-day aggregates from GET /workspace/summary (anchored to latest
 * interaction date so historical seed isn't all-zero).
 */
export function StatsStrip() {
  const { data } = useWorkspaceSummary("me");
  const stats = data?.stats;

  const ahtDelta = stats?.ahtDelta ?? "—";
  const ahtImproved = /^-/.test(ahtDelta.trim());

  const tiles = [
    {
      label: "Calls handled",
      value: (stats?.callsHandled ?? 0).toString(),
      delta: stats?.callsHandledDelta ?? "—",
      good: !/^-/.test((stats?.callsHandledDelta ?? "").trim()),
      icon: PhoneCall,
    },
    {
      label: "Avg handle time",
      value: stats?.aht ?? "—",
      delta: ahtDelta,
      good: ahtImproved,
      icon: Clock,
      invertArrow: true,
    },
    {
      label: "Resolutions",
      value: `${stats?.resolutions ?? 0}`,
      delta: `${stats?.resolutionRate ?? "0%"} rate`,
      good: true,
      icon: CheckCircle2,
    },
    {
      label: "Promises captured",
      value: (stats?.promisesCount ?? 0).toString(),
      delta: `₹${Math.round(stats?.promisesAmount ?? 0).toLocaleString("en-IN")}`,
      good: true,
      icon: HandCoins,
    },
  ];

  return (
    <div>
      {stats?.windowLabel && (
        <div className="mb-2 inline-flex items-center rounded-md bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-muted">
          {stats.windowLabel}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map((t, i) => {
          const Icon = t.icon;
          const Arrow = t.invertArrow
            ? t.good
              ? ArrowDownRight
              : ArrowUpRight
            : t.good
              ? ArrowUpRight
              : ArrowDownRight;
          return (
            <div
              key={t.label}
              className="animate-fade-up rounded-[12px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card"
              style={{ animationDelay: `${i * 30}ms` }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
                  {t.label}
                </span>
                <span className="grid h-7 w-7 place-items-center rounded-md bg-surface-sunken text-text-muted">
                  <Icon className="h-3.5 w-3.5" />
                </span>
              </div>
              <div className="mt-2.5 font-mono text-[28px] font-bold leading-none tracking-tight text-brand-navy tabular">
                {t.value}
              </div>
              <div
                className={cn(
                  "mt-2 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium",
                  t.good ? "bg-success-bg text-success" : "bg-danger-bg text-danger",
                )}
              >
                <Arrow className="h-3.5 w-3.5" />
                <span>{t.delta}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
