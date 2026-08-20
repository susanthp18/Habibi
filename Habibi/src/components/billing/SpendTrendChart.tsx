import { useMemo, useState } from "react";
import { type DayPoint, type Service, inrCompact } from "@/data/billing-seed";
import { ChartCard, ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";

export function SpendTrendChart({ data, services }: { data: DayPoint[]; services: Service[] }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const labels = useMemo(
    () =>
      data.map((d) =>
        new Date(d.date).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
      ),
    [data],
  );

  const series = useMemo(
    () =>
      services
        .filter((s) => !hidden.has(s.id))
        .map((s) => ({
          id: s.id,
          label: s.name,
          values: data.map((d) => d.values[s.id] ?? 0),
          color: s.color.startsWith("#") ? s.color : "#1868db",
        })),
    [data, services, hidden],
  );

  const totals = data.map((d) => Object.values(d.values).reduce((a, b) => a + b, 0));
  const periodTotal = totals.reduce((a, b) => a + b, 0);

  const fmtDay = (i: number) => labels[i] ?? "";

  return (
    <ChartCard
      title="Spend trend"
      subtitle="Daily cost by service"
      className="min-h-[17.5rem]"
      action={
        <div className="text-right">
          <div className="text-[10.5px] text-text-subtlest">Period total</div>
          <div className="text-body font-semibold tabular-nums text-text">{inrCompact(periodTotal)}</div>
        </div>
      }
    >
      <div className="mb-100 flex flex-wrap gap-050">
        {services.map((s) => {
          const on = !hidden.has(s.id);
          return (
            <button
              key={s.id}
              type="button"
              aria-pressed={on}
              onClick={() =>
                setHidden((prev) => {
                  const next = new Set(prev);
                  if (next.has(s.id)) next.delete(s.id);
                  else next.add(s.id);
                  return next;
                })
              }
              className={`inline-flex items-center gap-050 rounded-full px-075 py-025 text-[11px] transition-[background-color,opacity,transform] duration-150 active:scale-[0.96] ${
                on ? "bg-surface-sunken text-text" : "text-text-subtlest opacity-50"
              }`}
            >
              <span className="size-1.5 rounded-full" style={{ background: s.color }} />
              {s.name}
            </button>
          );
        })}
      </div>
      <ChartStage
        toolbar={
          <>
            <span className="text-[11px] tabular-nums text-text-subtlest">Daily burn</span>
            <SnapshotPill />
          </>
        }
      >
        {series.length === 0 ? (
          <div className="flex min-h-[13.75rem] items-center justify-center text-body-small text-text-subtlest">
            All series hidden.
          </div>
        ) : series.length === 1 ? (
          <LivelineTrend
            values={series[0].values}
            color={series[0].color}
            labels={labels}
            height={220}
            formatValue={inrCompact}
            formatTime={fmtDay}
            fill
          />
        ) : (
          <LivelineTrend
            series={series}
            labels={labels}
            height={220}
            formatValue={inrCompact}
            formatTime={fmtDay}
          />
        )}
      </ChartStage>
    </ChartCard>
  );
}
