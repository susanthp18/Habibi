import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
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
import { ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";
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

  const values = current.map((d) => d.values[service.id] ?? 0);
  const labels = current.map((d) => d.date);
  const stroke = service.color.startsWith("#") ? service.color : "#1868db";

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
            <ChartStage
              toolbar={
                <>
                  <span className="text-[11px] text-text-subtlest">Trend snapshot</span>
                  <SnapshotPill />
                </>
              }
            >
              <LivelineTrend
                values={values}
                labels={labels}
                color={stroke}
                height={160}
                formatValue={inrCompact}
                formatTime={(i) => labels[i]?.slice(5) ?? ""}
                fill
              />
            </ChartStage>
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
