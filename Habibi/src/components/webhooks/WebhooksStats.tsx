import { Activity, CheckCircle2, AlertTriangle, Radio } from "lucide-react";
import type { Delivery, Endpoint } from "@/data/webhooks-seed";
import { successRate, within } from "@/data/webhooks-seed";
import { cn } from "@/lib/utils";

export function WebhooksStats({
  endpoints,
  deliveries,
}: {
  endpoints: Endpoint[];
  deliveries: Delivery[];
}) {
  const active = endpoints.filter((e) => e.status === "active").length;
  const last24 = within(deliveries, 24);
  const rate = successRate(last24);
  const failing = deliveries.filter(
    (d) => d.status === "server_err" || d.status === "client_err",
  ).length;

  const tiles = [
    {
      label: "Endpoints",
      value: `${active}/${endpoints.length}`,
      hint: "active",
      icon: Radio,
      tone: "text-brand-primary",
    },
    {
      label: "Deliveries · 24h",
      value: last24.length.toString(),
      hint: `${deliveries.length} total`,
      icon: Activity,
      tone: "text-brand-navy",
    },
    {
      label: "Success · 24h",
      value: `${rate}%`,
      hint: rate >= 98 ? "healthy" : rate >= 90 ? "degraded" : "at risk",
      icon: CheckCircle2,
      tone:
        rate >= 98
          ? "text-emerald-600"
          : rate >= 90
            ? "text-amber-600"
            : "text-rose-600",
    },
    {
      label: "Retrying / failed",
      value: failing.toString(),
      hint: "across all endpoints",
      icon: AlertTriangle,
      tone: failing === 0 ? "text-emerald-600" : "text-rose-600",
    },
  ];

  return (
    <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-[var(--border-token)] bg-surface-app px-6 py-3 md:grid-cols-4">
      {tiles.map((t) => {
        const Icon = t.icon;
        return (
          <div
            key={t.label}
            className="rounded-lg border border-[var(--border-token)] bg-surface-card p-3"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
                {t.label}
              </span>
              <Icon className={cn("h-4 w-4", t.tone)} />
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className={cn("text-[22px] font-semibold", t.tone)}>
                {t.value}
              </span>
              <span className="text-[11px] text-text-muted">{t.hint}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
