import { FileClock, Loader2, Send, AlertTriangle, Timer } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface Metrics {
  openCount: number;
  generatingCount: number;
  sentTodayCount: number;
  failedCount: number;
  avgFulfilMins: number;
}

function Tile({
  label,
  value,
  sub,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: LucideIcon;
  tone: "brand" | "amber" | "emerald" | "red" | "slate";
}) {
  const toneMap = {
    brand: "text-brand-primary bg-brand-tint",
    amber: "text-amber-700 bg-amber-100",
    emerald: "text-emerald-700 bg-emerald-100",
    red: "text-red-700 bg-red-100",
    slate: "text-text-secondary bg-surface-sunken",
  }[tone];
  return (
    <div className="flex items-center gap-2 rounded-lg border border-[var(--border-token)] bg-surface-card px-3 py-2">
      <div className={cn("grid h-8 w-8 place-items-center rounded-md", toneMap)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-[10.5px] uppercase tracking-wide text-text-muted">{label}</div>
        <div className="text-[15px] font-semibold text-brand-navy leading-tight tabular-nums">{value}</div>
        {sub && <div className="text-[10.5px] text-text-muted">{sub}</div>}
      </div>
    </div>
  );
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <div className="grid shrink-0 grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
      <Tile label="Open" value={m.openCount} icon={FileClock} tone="brand" sub="Requested + generating" />
      <Tile label="Generating" value={m.generatingCount} icon={Loader2} tone="amber" sub="In flight" />
      <Tile label="Sent today" value={m.sentTodayCount} icon={Send} tone="emerald" sub="Last 24h" />
      <Tile label="Failed" value={m.failedCount} icon={AlertTriangle} tone="red" sub="Needs retry" />
      <Tile
        label="Avg fulfilment"
        value={m.avgFulfilMins < 60 ? `${m.avgFulfilMins}m` : `${(m.avgFulfilMins / 60).toFixed(1)}h`}
        icon={Timer}
        tone="slate"
        sub="Request → delivered"
      />
    </div>
  );
}
