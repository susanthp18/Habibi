import { ArrowDown, ArrowUp, Minus, Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentQaStat } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";

export function AgentTrendsTable({
  stats,
  activeAgent,
  onSelect,
}: {
  stats: AgentQaStat[];
  activeAgent: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <table className="w-full border-collapse text-[12px]">
        <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-muted">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Agent</th>
            <th className="px-3 py-2 text-left font-medium">Scored</th>
            <th className="px-3 py-2 text-left font-medium">Avg score</th>
            <th className="px-3 py-2 text-left font-medium">Δ 7d</th>
            <th className="px-3 py-2 text-left font-medium">Weakest</th>
            <th className="px-3 py-2 text-right font-medium">Coaching</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border-token)]">
          {stats.map((s) => {
            const Icon = s.isBot ? Bot : User;
            const Trend = s.delta7d > 0.5 ? ArrowUp : s.delta7d < -0.5 ? ArrowDown : Minus;
            return (
              <tr
                key={s.agentId}
                onClick={() => onSelect(s.agentId)}
                className={cn(
                  "cursor-pointer hover:bg-surface-sunken",
                  activeAgent === s.agentId && "bg-brand-tint",
                )}
              >
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5 font-medium text-brand-navy">
                    <Icon className="h-3.5 w-3.5 text-text-muted" />
                    {s.agentId}
                  </div>
                </td>
                <td className="px-3 py-2">{s.scored}</td>
                <td className="px-3 py-2"><ScoreBand total={s.avg} size="sm" /></td>
                <td className={cn(
                  "px-3 py-2",
                  s.delta7d > 0.5 ? "text-emerald-700" : s.delta7d < -0.5 ? "text-red-700" : "text-text-muted",
                )}>
                  <span className="inline-flex items-center gap-0.5">
                    <Trend className="h-3 w-3" /> {Math.abs(s.delta7d).toFixed(1)}
                  </span>
                </td>
                <td className="px-3 py-2 text-text-secondary">{s.weakestSection}</td>
                <td className="px-3 py-2 text-right">
                  {s.openCoaching > 0 ? (
                    <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                      {s.openCoaching} open
                    </span>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
