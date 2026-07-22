import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  TENANTS,
  changePct,
  inr,
  inrCompact,
  sumRange,
  usageUnits,
  type DayPoint,
  type Service,
} from "@/data/billing-seed";
import { cn } from "@/lib/utils";

export function ServiceDrawer({
  open,
  onOpenChange,
  service,
  current,
  previous,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  service: Service | null;
  current: DayPoint[];
  previous: DayPoint[];
}) {
  if (!service) return null;
  const cost = sumRange(current, service.id);
  const prev = sumRange(previous, service.id);
  const delta = changePct(cost, prev);
  const units = usageUnits(cost, service.unitCostInr);

  const series = current.map((d) => ({ date: d.date, v: d.values[service.id] ?? 0 }));

  const tenantRows = TENANTS.map((t) => ({
    ...t,
    spend: cost * t.spendShare,
  })).sort((a, b) => b.spend - a.spend);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full max-w-[520px] flex-col overflow-hidden p-0 sm:max-w-[520px]">
        <SheetHeader className="shrink-0 border-b border-[var(--border-token)] px-6 py-4">
          <SheetTitle className="flex items-center gap-2 text-[15px] font-semibold text-brand-navy">
            <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: service.color }} />
            {service.name}
          </SheetTitle>
          <p className="text-[11px] text-text-secondary">
            {service.provider} · {service.category} · {inr(service.unitCostInr)} per {service.unit}
          </p>
        </SheetHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
          <div className="grid grid-cols-3 gap-3">
            <Tile label="Spend" value={inrCompact(cost)} />
            <Tile label="Usage" value={`${units >= 1000 ? (units / 1000).toFixed(1) + "k" : units.toFixed(1)} ${service.unit}`} />
            <Tile
              label="Δ vs prev"
              value={`${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
              tone={delta >= 0 ? "bad" : "good"}
            />
          </div>

          <div>
            <div className="mb-1 text-[12px] font-semibold text-brand-navy">Daily spend</div>
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
                    contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid var(--border-token)", background: "var(--surface-card)" }}
                    formatter={(v: number) => inrCompact(v)}
                  />
                  <Area type="monotone" dataKey="v" stroke={service.color} strokeWidth={1.5} fill={`url(#fill-${service.id})`} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div>
            <div className="mb-1 text-[12px] font-semibold text-brand-navy">Top tenants driving this cost</div>
            <div className="space-y-1.5">
              {tenantRows.map((t) => (
                <div key={t.id} className="flex items-center gap-2 rounded-md border border-[var(--border-token)] px-3 py-2 text-[12px]">
                  <span className="flex-1 truncate font-medium text-brand-navy">{t.name}</span>
                  <span className="font-mono text-text-secondary">{inrCompact(t.spend)}</span>
                  <span className="w-14 text-right text-[10.5px] text-text-muted">
                    {(t.spendShare * 100).toFixed(0)}%
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
    <div className="rounded-md border border-[var(--border-token)] p-3">
      <div className="text-[10.5px] font-medium uppercase tracking-wider text-text-muted">{label}</div>
      <div
        className={cn(
          "mt-1 text-[16px] font-semibold",
          tone === "good" && "text-emerald-600",
          tone === "bad" && "text-rose-600",
          !tone && "text-brand-navy",
        )}
      >
        {value}
      </div>
    </div>
  );
}
