import { Activity, AlertTriangle, Clock, PhoneCall, ShieldCheck, Smile } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";

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
  const tone = deltaTone === "good" ? "success" : deltaTone === "bad" ? "danger" : "neutral";
  return (
    <div className="flex min-w-0 flex-1 items-center gap-150 rounded-large border border-border bg-surface px-150 py-100">
      <div className="grid h-400 w-400 shrink-0 place-items-center rounded-medium bg-background-brand-subtlest text-text-brand">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-050 text-body-small font-semibold text-text-subtlest">
          {label}
          {live && <span className="h-1.5 w-1.5 pulse-dot rounded-full bg-background-success" />}
        </div>
        <div className="tabular truncate text-[1.25rem] font-semibold leading-tight text-text">
          {value}
        </div>
      </div>
      {delta && (
        <Lozenge tone={tone} className="shrink-0">
          {delta}
        </Lozenge>
      )}
    </div>
  );
}

export function StatsStrip({ stats }: { stats: StatValue }) {
  return (
    <div className="grid shrink-0 grid-cols-2 gap-100 border-b border-border bg-surface px-200 py-150 md:grid-cols-3 xl:grid-cols-6">
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
