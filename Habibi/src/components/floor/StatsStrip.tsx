import { Activity, AlertTriangle, Bot, Clock, PhoneCall, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FloorStats } from "@/api/floor";

export type FloorFocus = "all" | "critical" | "queue" | "bot-risk" | "human";

const fmtWait = (s: number) => {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
};

const signed = (n: number) => (n >= 0 ? `+${n.toFixed(2)}` : n.toFixed(2));

type TileProps = {
  label: string;
  value: string;
  icon: LucideIcon;
  live?: boolean;
  active?: boolean;
  tone?: "default" | "danger" | "warning";
  onClick?: () => void;
};

function Tile({ label, value, icon: Icon, live, active, tone = "default", onClick }: TileProps) {
  const iconTone =
    tone === "danger"
      ? "bg-background-danger text-text-danger"
      : tone === "warning"
        ? "bg-background-warning text-text-warning"
        : "bg-background-brand-subtlest text-text-brand";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-w-0 flex-1 items-center gap-150 rounded-large border bg-surface px-150 py-100 text-left transition-colors",
        active
          ? "border-border-brand bg-background-brand-subtlest/40"
          : "border-border hover:bg-surface-sunken",
      )}
    >
      <div className={cn("grid h-400 w-400 shrink-0 place-items-center rounded-medium", iconTone)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-050 text-body-small font-semibold text-text-subtlest">
          {label}
          {live && <span className="h-1.5 w-1.5 pulse-dot rounded-full bg-background-success" />}
        </div>
        <div className="tabular truncate heading-medium font-semibold leading-tight text-text">
          {value}
        </div>
      </div>
    </button>
  );
}

export function StatsStrip({
  stats,
  focus,
  onFocus,
}: {
  stats: FloorStats;
  focus: FloorFocus;
  onFocus: (next: FloorFocus) => void;
}) {
  const toggle = (key: FloorFocus) => onFocus(focus === key ? "all" : key);
  return (
    <div className="grid shrink-0 grid-cols-2 gap-100 border-b border-border bg-surface px-200 py-150 md:grid-cols-4 xl:grid-cols-8">
      <Tile
        label="Live now"
        value={String(stats.callsInProgress)}
        icon={PhoneCall}
        live
        active={focus === "all"}
        onClick={() => onFocus("all")}
      />
      <Tile
        label="Need you"
        value={String(stats.criticalAlerts)}
        icon={AlertTriangle}
        tone={stats.criticalAlerts > 0 ? "danger" : "default"}
        active={focus === "critical"}
        onClick={() => toggle("critical")}
      />
      <Tile
        label="Waiting"
        value={String(stats.queueDepth)}
        icon={Activity}
        tone={stats.queueDepth > 0 ? "warning" : "default"}
        active={focus === "queue"}
        onClick={() => toggle("queue")}
      />
      <Tile
        label="Longest wait"
        value={fmtWait(stats.longestWaitSec)}
        icon={Clock}
        tone={stats.longestWaitSec > 120 ? "warning" : "default"}
        active={focus === "queue"}
        onClick={() => toggle("queue")}
      />
      <Tile
        label="Agents free"
        value={String(stats.agentsAvailable)}
        icon={Users}
        onClick={() => onFocus("all")}
      />
      <Tile
        label="On a call"
        value={String(stats.agentsOnCall)}
        icon={Users}
        active={focus === "human"}
        onClick={() => toggle("human")}
      />
      <Tile
        label="Bots at risk"
        value={String(stats.botAtRisk)}
        icon={Bot}
        tone={stats.botAtRisk > 0 ? "warning" : "default"}
        active={focus === "bot-risk"}
        onClick={() => toggle("bot-risk")}
      />
      <Tile
        label="Avg sentiment"
        value={signed(stats.avgSentiment)}
        icon={Activity}
        tone={stats.avgSentiment < 0 ? "danger" : "default"}
        onClick={() => onFocus("all")}
      />
    </div>
  );
}
