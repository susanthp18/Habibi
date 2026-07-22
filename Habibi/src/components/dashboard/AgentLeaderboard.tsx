import { Medal, Trophy } from "lucide-react";
import type { LeaderRow } from "@/data/dashboard-seed";
import { cn } from "@/lib/utils";

function medalTone(rank: number) {
  if (rank === 1) return "text-warning";
  if (rank === 2) return "text-text-secondary";
  if (rank === 3) return "text-brand-primary-dark";
  return "text-text-muted";
}

export function AgentLeaderboard({ rows, onOpen }: { rows: LeaderRow[]; onOpen?: (r: LeaderRow) => void }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface-card shadow-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-brand-navy">Agent leaderboard</h3>
          <p className="text-xs text-text-secondary">Top performers this period</p>
        </div>
        <Trophy className="h-4 w-4 text-warning" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface-sunken text-[11px] uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-2 text-left font-medium">#</th>
              <th className="px-4 py-2 text-left font-medium">Agent</th>
              <th className="px-4 py-2 text-right font-medium">Calls</th>
              <th className="px-4 py-2 text-right font-medium">AHT</th>
              <th className="px-4 py-2 text-right font-medium">Upsell</th>
              <th className="px-4 py-2 text-right font-medium">CSAT</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.rank}
                onClick={() => onOpen?.(r)}
                className="cursor-pointer border-t border-border transition-colors hover:bg-brand-tint/40"
              >
                <td className="px-4 py-2.5 align-middle">
                  <span className={cn("inline-flex items-center gap-1 text-xs font-semibold tabular", medalTone(r.rank))}>
                    {r.rank <= 3 ? <Medal className="h-3.5 w-3.5" /> : null}
                    {r.rank}
                  </span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="text-sm font-medium text-text-primary">{r.name}</div>
                  <div className="text-[11px] text-text-muted">{r.team}</div>
                </td>
                <td className="px-4 py-2.5 text-right tabular">{r.calls}</td>
                <td className="px-4 py-2.5 text-right tabular">{r.aht}</td>
                <td className="px-4 py-2.5 text-right tabular text-success">{r.upsell.toFixed(1)}%</td>
                <td className="px-4 py-2.5 text-right tabular">{r.csat.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
