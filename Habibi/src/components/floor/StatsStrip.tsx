import { Activity, AlertTriangle, Clock, PhoneCall, ShieldCheck, Smile } from "lucide-react";
import type { LucideIcon } from "lucide-react";

type StatValue = {
  callsInProgress: number;
  avgSentiment: number;
  escalationRate: number;
  queueDepth: number;
  botContainment: number;
  longestWaitSec: number;
};

const fmtWait = (s: number) => {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
};

const pct = (n: number) => `${(n * 100).toFixed(0)}%`;
const signed = (n: number) => (n >= 0 ? `+${n.toFixed(2)}` : n.toFixed(2));

type TileProps = {
  label: string;
  value: string;
  delta?: string;
  deltaTone?: "good" | "bad" | "neutral";
  icon: LucideIcon;
  live?: boolean;
};

function Tile({ label, value, delta, deltaTone = "neutral", icon: Icon, live }: TileProps) {
  const toneCls =
    deltaTone === "good"
      ? "bg-success-bg text-success"
      : deltaTone === "bad"
        ? "bg-danger-bg text-danger"
        : "bg-surface-sunken text-text-secondary";
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3 rounded-lg border border-[var(--border-token)] bg-surface-card px-3 py-2 shadow-card">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-brand-tint text-brand-primary-dark">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
          {label}
          {live && <span className="h-1.5 w-1.5 pulse-dot rounded-full bg-success" />}
        </div>
        <div className="tabular truncate text-[18px] font-semibold leading-tight text-brand-navy">
          {value}
        </div>
      </div>
      {delta && (
        <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${toneCls}`}>
          {delta}
        </span>
      )}
    </div>
  );
}

export function StatsStrip({ stats }: { stats: StatValue }) {
  return (
    <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-[var(--border-token)] bg-surface-app px-4 py-3 md:grid-cols-3 xl:grid-cols-6">
      <Tile
        label="Calls in progress"
        value={String(stats.callsInProgress)}
        delta="+3 vs 1h"
        deltaTone="neutral"
        icon={PhoneCall}
        live
      />
      <Tile
        label="Avg sentiment"
        value={signed(stats.avgSentiment)}
        delta={stats.avgSentiment >= 0 ? "trending up" : "trending down"}
        deltaTone={stats.avgSentiment >= 0 ? "good" : "bad"}
        icon={Smile}
      />
      <Tile
        label="Escalation rate"
        value={pct(stats.escalationRate)}
        delta="+2pp"
        deltaTone="bad"
        icon={AlertTriangle}
      />
      <Tile
        label="Queue depth"
        value={String(stats.queueDepth)}
        delta="stable"
        deltaTone="neutral"
        icon={Activity}
      />
      <Tile
        label="Bot containment"
        value={pct(stats.botContainment)}
        delta="+4pp"
        deltaTone="good"
        icon={ShieldCheck}
      />
      <Tile
        label="Longest wait"
        value={fmtWait(stats.longestWaitSec)}
        delta="watch"
        deltaTone="bad"
        icon={Clock}
      />
    </div>
  );
}
