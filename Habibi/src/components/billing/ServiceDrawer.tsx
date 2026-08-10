import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  changePct,
  inr,
  inrCompact,
  sumRange,
  usageUnits,
  type DayPoint,
  type Service,
  type Tenant,
} from "@/data/billing-seed";
import { cn } from "@/lib/utils";

export function ServiceDrawer({
  open,
  onOpenChange,
  service,
  current,
  previous,
  tenants,
  serviceTenantSpend,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  service: Service | null;
  current: DayPoint[];
  previous: DayPoint[];
  tenants: Tenant[];
  serviceTenantSpend: Record<string, number>;
}) {
  if (!service) return null;
  const cost = sumRange(current, service.id);
  const prev = sumRange(previous, service.id);
  const delta = changePct(cost, prev);
  const units = usageUnits(cost, service.unitCostInr);

  const series = current.map((d) => ({ date: d.date, v: d.values[service.id] ?? 0 }));

  const tenantRows = tenants
    .map((t) => ({
      ...t,
      spend: serviceTenantSpend[t.id] ?? 0,
    }))
    .filter((t) => t.spend > 0)
    .sort((a, b) => b.spend - a.spend)
    .slice(0, 10);
  const tenantTotal = tenants.reduce((s, t) => s + (serviceTenantSpend[t.id] ?? 0), 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full max-w-[37.5rem] flex-col overflow-hidden p-0 sm:max-w-[37.5rem]">
        <SheetHeader className="shrink-0 border-b border-border px-300 py-200">
          <SheetTitle className="flex items-center gap-100 text-[0.875rem] font-semibold text-text">
            <span className="h-3 w-3 rounded-small" style={{ backgroundColor: service.color }} />
            {service.name}
          </SheetTitle>
          <p className="text-body-small text-text-subtle">
            {service.provider} · {service.category} · {inr(service.unitCostInr)} per {service.unit}
          </p>
        </SheetHeader>

        <div className="min-h-0 flex-1 space-y-200 overflow-y-auto px-300 py-200">
          <div className="grid grid-cols-3 gap-150">
            <Tile label="Spend" value={inrCompact(cost)} />
            <Tile
              label="Usage"
              value={`${units >= 1000 ? (units / 1000).toFixed(1) + "k" : units.toFixed(1)} ${service.unit}`}
            />
            <Tile
              label="Δ vs prev"
              value={`${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
              tone={delta >= 0 ? "bad" : "good"}
            />
          </div>

          <div>
            <div className="mb-050 text-body-small font-semibold text-text">Daily spend</div>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={series} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`fill-${service.id}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={service.color} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={service.color} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" hide />
                  <YAxis hide />
                  <Tooltip
                    contentStyle={{
                      fontSize: 11,
                      borderRadius: 8,
                      border: "1px solid var(--border)",
                      background: "var(--surface)",
                    }}
                    formatter={(v: number) => inrCompact(v)}
                  />
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke={service.color}
                    strokeWidth={1.5}
                    fill={`url(#fill-${service.id})`}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div>
            <div className="mb-050 text-body-small font-semibold text-text">Top tenants driving this cost</div>
            <div className="space-y-075">
              {tenantRows.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center gap-100 rounded-medium border border-border px-150 py-100 text-body-small"
                >
                  <span className="flex-1 truncate font-medium text-text">{t.name}</span>
                  <span className="font-mono text-text-subtle">{inrCompact(t.spend)}</span>
                  <span className="w-14 text-right text-body-small text-text-subtlest">
                    {tenantTotal > 0 ? ((t.spend / tenantTotal) * 100).toFixed(0) : 0}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-medium border border-border p-150">
      <div className="text-body-small font-medium text-text-subtlest">{label}</div>
      <div
        className={cn(
          "mt-050 text-[1rem] font-semibold",
          tone === "good" && "text-text-success",
          tone === "bad" && "text-text-danger",
          !tone && "text-text",
        )}
      >
        {value}
      </div>
    </div>
  );
}
