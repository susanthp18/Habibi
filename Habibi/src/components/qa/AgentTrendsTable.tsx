import { ArrowDown, ArrowUp, Minus, Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentQaStat } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";
import { Lozenge } from "@/components/ui/lozenge";

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
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      <table className="w-full border-collapse text-body-small">
        <thead className="bg-surface-sunken text-body-small text-text-subtlest">
          <tr>
            <th className="px-150 py-100 text-left font-medium">Agent</th>
            <th className="px-150 py-100 text-left font-medium">Scored</th>
            <th className="px-150 py-100 text-left font-medium">Avg score</th>
            <th className="px-150 py-100 text-left font-medium">Δ 7d</th>
            <th className="px-150 py-100 text-left font-medium">Weakest</th>
            <th className="px-150 py-100 text-right font-medium">Coaching</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {stats.map((s) => {
            const Icon = s.isBot ? Bot : User;
            const Trend = s.delta7d > 0.5 ? ArrowUp : s.delta7d < -0.5 ? ArrowDown : Minus;
            return (
              <tr
                key={s.agentId}
                onClick={() => onSelect(s.agentId)}
                className={cn(
                  "cursor-pointer hover:bg-surface-sunken",
                  activeAgent === s.agentId && "bg-background-brand-subtlest",
                )}
              >
                <td className="px-150 py-100">
                  <div className="flex items-center gap-075 font-medium text-text">
                    <Icon className="h-3.5 w-3.5 text-text-subtlest" />
                    {s.agentId}
                  </div>
                </td>
                <td className="px-150 py-100">{s.scored}</td>
                <td className="px-150 py-100"><ScoreBand total={s.avg} size="sm" /></td>
                <td className={cn(
                  "px-150 py-100",
                  s.delta7d > 0.5 ? "text-text-success-bolder" : s.delta7d < -0.5 ? "text-text-danger-bolder" : "text-text-subtlest",
                )}>
                  <span className="inline-flex items-center gap-025">
                    <Trend className="h-3 w-3" /> {Math.abs(s.delta7d).toFixed(1)}
                  </span>
                </td>
                <td className="px-150 py-100 text-text-subtle">{s.weakestSection}</td>
                <td className="px-150 py-100 text-right">
                  {s.openCoaching > 0 ? (
                    <Lozenge tone="warning">
                      {s.openCoaching} open
                    </Lozenge>
                  ) : (
                    <span className="text-text-subtlest">—</span>
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
