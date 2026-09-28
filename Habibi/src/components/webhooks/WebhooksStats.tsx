import { Activity, CheckCircle2, AlertTriangle, Radio } from "lucide-react";
import type { Delivery, Endpoint } from "@/api/types/webhooks";
import { successRate, within } from "@/lib/webhooks";
import { cn } from "@/lib/utils";

export function WebhooksStats({
  endpoints,
  deliveries,
}: {
  endpoints: Endpoint[];
  deliveries: Delivery[];
}) {
  const active = endpoints.filter((e) => e.status === "active" && e.subscriptionsConfirmed).length;
  const business = deliveries.filter((d) => d.mode !== "simulated" && d.event !== "webhook.test");
  const last24 = within(business, 24);
  const settled = last24.filter((d) => d.status !== "pending");
  const rate = successRate(settled);
  const failing = business.filter((d) => d.status !== "success").length;

  const tiles = [
    {
      label: "Endpoints",
      value: `${active}/${endpoints.length}`,
      hint: "active",
      icon: Radio,
      tone: "text-text-brand",
    },
    {
      label: "Deliveries · 24h",
      value: last24.length.toString(),
      hint: `${business.length} total`,
      icon: Activity,
      tone: "text-text",
    },
    {
      label: "Success · 24h",
      value: settled.length ? `${rate}%` : "—",
      hint: settled.length
        ? rate >= 98
          ? "healthy"
          : rate >= 90
            ? "degraded"
            : "at risk"
        : "no settled deliveries",
      icon: CheckCircle2,
      tone:
        rate >= 98
          ? "text-text-code-default"
          : rate >= 90
            ? "text-text-warning"
            : "text-text-danger",
    },
    {
      label: "Retrying / failed",
      value: failing.toString(),
      hint: "across all endpoints",
      icon: AlertTriangle,
      tone: failing === 0 ? "text-text-code-default" : "text-text-danger",
    },
  ];

  return (
    <div className="grid shrink-0 grid-cols-2 gap-150 border-b border-border bg-surface px-300 py-150 md:grid-cols-4">
      {tiles.map((t) => {
        const Icon = t.icon;
        return (
          <div key={t.label} className="rounded-large border border-border bg-surface p-150">
            <div className="flex items-center justify-between">
              <span className="text-body-small font-medium text-text-subtlest">{t.label}</span>
              <Icon className={cn("h-4 w-4", t.tone)} />
            </div>
            <div className="mt-050 flex items-baseline gap-100">
              <span className={cn("heading-large font-semibold", t.tone)}>{t.value}</span>
              <span className="text-body-small text-text-subtlest">{t.hint}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
