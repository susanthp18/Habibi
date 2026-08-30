import { CalendarClock, Timer, PhoneOff, CheckCircle2, UserX } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface Metrics {
  scheduledToday: number;
  dueNextHour: number;
  missed7d: number;
  completionRate: number;
  unassigned: number;
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
    brand: "text-text-brand bg-background-brand-subtlest",
    amber: "text-text-warning-bolder bg-background-warning-subtler",
    emerald: "text-text-success-bolder bg-background-success-subtler",
    red: "text-text-danger-bolder bg-background-danger-subtler",
    slate: "text-text-subtle bg-surface-sunken",
  }[tone];
  return (
    <div className="flex items-center gap-100 rounded-large border border-border bg-surface px-150 py-100">
      <div className={cn("grid h-400 w-400 place-items-center rounded-medium", toneMap)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-body-small text-text-subtlest">{label}</div>
        <div className="text-body font-semibold text-text leading-tight tabular-nums">{value}</div>
        {sub && <div className="text-body-small text-text-subtlest">{sub}</div>}
      </div>
    </div>
  );
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <div className="grid shrink-0 grid-cols-2 gap-100 md:grid-cols-3 xl:grid-cols-5">
      <Tile
        label="Scheduled today"
        value={m.scheduledToday}
        icon={CalendarClock}
        tone="brand"
        sub="Open + reminded"
      />
      <Tile
        label="Due next hour"
        value={m.dueNextHour}
        icon={Timer}
        tone="amber"
        sub="Prep or dial"
      />
      <Tile
        label="Missed (7d)"
        value={m.missed7d}
        icon={PhoneOff}
        tone="red"
        sub="Needs recovery"
      />
      <Tile
        label="Completion (7d)"
        value={`${m.completionRate}%`}
        icon={CheckCircle2}
        tone="emerald"
        sub="Completed / total"
      />
      <Tile
        label="Unassigned"
        value={m.unassigned}
        icon={UserX}
        tone="slate"
        sub="Awaiting owner"
      />
    </div>
  );
}
