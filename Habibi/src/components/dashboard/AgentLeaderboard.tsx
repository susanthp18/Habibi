import { useMemo } from "react";
import { Medal, Trophy } from "lucide-react";
import type { LeaderRow } from "@/data/dashboard-seed";
import { cn } from "@/lib/utils";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";

function medalTone(rank: number) {
  if (rank === 1) return "text-text-warning";
  if (rank === 2) return "text-text-subtle";
  if (rank === 3) return "text-text-brand";
  return "text-text-subtlest";
}

export function AgentLeaderboard({
  rows,
  onOpen,
}: {
  rows: LeaderRow[];
  onOpen?: (r: LeaderRow) => void;
}) {
  const columns = useMemo<RecordsColumn<LeaderRow>[]>(
    () => [
      {
        id: "rank",
        header: "#",
        sortable: true,
        sortValue: (r) => r.rank,
        className: "min-w-[3.5rem] whitespace-nowrap",
        cell: (r) => (
          <span
            className={cn(
              "inline-flex items-center gap-050 text-body-small font-semibold tabular",
              medalTone(r.rank),
            )}
          >
            {r.rank <= 3 ? <Medal className="h-3.5 w-3.5" /> : null}
            {r.rank}
          </span>
        ),
      },
      {
        id: "agent",
        header: "Agent",
        sticky: true,
        sortable: true,
        sortValue: (r) => r.name,
        className: "min-w-[11rem]",
        cell: (r) => (
          <div className="flex min-w-0 items-center gap-100">
            <RecordsAvatarMark label={r.name} />
            <span className="min-w-0">
              <span className="block truncate text-body font-medium text-text">{r.name}</span>
              <span className="block truncate text-body-small text-text-subtlest">{r.team}</span>
            </span>
          </div>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">agents</span>
          </span>
        ),
      },
      {
        id: "calls",
        header: "Calls",
        sortable: true,
        sortValue: (r) => r.calls,
        align: "right",
        className: "min-w-[4.5rem] whitespace-nowrap",
        cell: (r) => <span className="tabular-nums text-text">{r.calls}</span>,
        footer: (visible) => (
          <span className="tabular-nums">
            {visible.reduce((s, r) => s + r.calls, 0).toLocaleString("en-IN")}
          </span>
        ),
      },
      {
        id: "aht",
        header: "AHT",
        sortable: true,
        sortValue: (r) => r.aht,
        align: "right",
        className: "min-w-[5rem] whitespace-nowrap",
        cell: (r) => <span className="tabular-nums text-text-subtle">{r.aht}</span>,
      },
      {
        id: "upsell",
        header: "Upsell",
        sortable: true,
        sortValue: (r) => r.upsell ?? -1,
        align: "right",
        className: "min-w-[5rem] whitespace-nowrap",
        cell: (r) =>
          r.upsell == null ? (
            <span className="text-text-subtlest">—</span>
          ) : (
            <span className="tabular-nums text-text-success">{r.upsell.toFixed(1)}%</span>
          ),
      },
      {
        id: "csat",
        header: "CSAT",
        sortable: true,
        sortValue: (r) => r.csat ?? -1,
        align: "right",
        className: "min-w-[4.5rem] whitespace-nowrap",
        cell: (r) =>
          r.csat == null ? (
            <span className="text-text-subtlest">—</span>
          ) : (
            <span className="tabular-nums text-text">{r.csat.toFixed(2)}</span>
          ),
      },
    ],
    [],
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-200 py-150">
        <div>
          <h3 className="text-sm font-semibold text-text">Agent leaderboard</h3>
          <p className="text-xs text-text-subtle">Top performers this period</p>
        </div>
        <Trophy className="h-4 w-4 text-text-warning" />
      </div>
      <RecordsTable
        rows={rows}
        getRowId={(r) => `${r.rank}-${r.name}`}
        columns={columns}
        defaultSort={{ id: "rank", dir: 1 }}
        onRowClick={onOpen}
        ariaLabel="Agent leaderboard"
        tableClassName="min-w-[36rem]"
        className="min-h-0 flex-1 rounded-none border-0"
        emptyMessage="No agent activity in this period."
      />
    </div>
  );
}
