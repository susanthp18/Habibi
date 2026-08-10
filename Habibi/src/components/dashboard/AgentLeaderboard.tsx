import { Medal, Trophy } from "lucide-react";
import type { LeaderRow } from "@/data/dashboard-seed";
import { cn } from "@/lib/utils";

function medalTone(rank: number) {
  if (rank === 1) return "text-text-warning";
  if (rank === 2) return "text-text-subtle";
  if (rank === 3) return "text-text-brand";
  return "text-text-subtlest";
}

export function AgentLeaderboard({ rows, onOpen }: { rows: LeaderRow[]; onOpen?: (r: LeaderRow) => void }) {
  return (
    <div className="flex h-full flex-col rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-200 py-150">
        <div>
          <h3 className="text-sm font-semibold text-text">Agent leaderboard</h3>
          <p className="text-xs text-text-subtle">Top performers this period</p>
        </div>
        <Trophy className="h-4 w-4 text-text-warning" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface-sunken text-body-small text-text-subtle">
            <tr>
              <th className="px-200 py-100 text-left font-medium">#</th>
              <th className="px-200 py-100 text-left font-medium">Agent</th>
              <th className="px-200 py-100 text-right font-medium">Calls</th>
              <th className="px-200 py-100 text-right font-medium">AHT</th>
              <th className="px-200 py-100 text-right font-medium">Upsell</th>
              <th className="px-200 py-100 text-right font-medium">CSAT</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.rank}
                onClick={() => onOpen?.(r)}
                className="cursor-pointer border-t border-border transition-colors hover:bg-background-brand-subtlest/40"
              >
                <td className="px-200 py-150 align-middle">
                  <span className={cn("inline-flex items-center gap-050 text-xs font-semibold tabular", medalTone(r.rank))}>
                    {r.rank <= 3 ? <Medal className="h-3.5 w-3.5" /> : null}
                    {r.rank}
                  </span>
                </td>
                <td className="px-200 py-150">
                  <div className="text-sm font-medium text-text">{r.name}</div>
                  <div className="text-body-small text-text-subtlest">{r.team}</div>
                </td>
                <td className="px-200 py-150 text-right tabular">{r.calls}</td>
                <td className="px-200 py-150 text-right tabular">{r.aht}</td>
                {/* A dash, not a number: the rep captured no leads in this
                    window. This column used to be `12 + rank * 1.3`. */}
                <td className="px-200 py-150 text-right tabular text-text-success">
                  {r.upsell == null ? (
                    <span className="text-text-subtlest">—</span>
                  ) : (
                    `${r.upsell.toFixed(1)}%`
                  )}
                </td>
                <td className="px-200 py-150 text-right tabular">
                  {r.csat == null ? (
                    <span className="text-text-subtlest">—</span>
                  ) : (
                    r.csat.toFixed(2)
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-200 py-400 text-center text-body-small text-text-subtle">
                  No agent activity in this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
