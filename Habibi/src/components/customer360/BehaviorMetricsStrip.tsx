import type { BehaviorMetrics } from "@/lib/customerInsights";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

export function BehaviorMetricsStrip({ metrics }: { metrics: BehaviorMetrics }) {
  const tiles = [
    {
      label: "PTP keep-rate",
      value: metrics.ptpKeepRate !== null ? `${metrics.ptpKeepRate}%` : "—",
      tone: "brand" as const,
    },
    {
      label: "Days since contact",
      value: metrics.daysSinceContact !== null ? String(metrics.daysSinceContact) : "—",
      tone: metrics.daysSinceContact !== null && metrics.daysSinceContact >= 7 ? ("warning" as const) : ("default" as const),
    },
    {
      label: "Open dispute $",
      value: fmtMoney(metrics.openDisputeAmount),
      tone: metrics.openDisputeAmount > 0 ? ("warning" as const) : ("default" as const),
    },
    {
      label: "Next EMI",
      value: metrics.nextEmiAmount !== null ? fmtMoney(metrics.nextEmiAmount) : "—",
      sub: metrics.nextEmiDate ? fmtDate(metrics.nextEmiDate) : undefined,
      tone: "default" as const,
    },
    {
      label: "Payment streak",
      value: `${metrics.paymentStreak}`,
      tone: "success" as const,
    },
    {
      label: "Active PTP $",
      value: fmtMoney(metrics.activePromiseAmount),
      tone: "default" as const,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-100 sm:grid-cols-3 xl:grid-cols-6">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-large border border-border bg-surface p-150">
          <div className="text-body-small font-semibold text-text-subtle">{t.label}</div>
          <div
            className={cn(
              "mt-025 text-lg font-semibold tabular",
              t.tone === "brand" && "text-text-brand",
              t.tone === "success" && "text-text-success",
              t.tone === "warning" && "text-text-warning",
              t.tone === "default" && "text-text",
            )}
          >
            {t.value}
          </div>
          {t.sub ? <div className="text-body-small text-text-subtlest tabular">{t.sub}</div> : null}
        </div>
      ))}
    </div>
  );
}
