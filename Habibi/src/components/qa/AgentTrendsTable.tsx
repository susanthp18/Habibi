import { useMemo } from "react";
import { ArrowDown, ArrowUp, Minus, Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentQaStat } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

export function AgentTrendsTable({
  stats,
  activeAgent,
  onSelect,
}: {
  stats: AgentQaStat[];
  activeAgent: string | null;
  onSelect: (id: string) => void;
}) {
  const columns = useMemo<RecordsColumn<AgentQaStat>[]>(
    () => [
      {
        id: "agent",
        header: "Agent",
        sticky: true,
        sortable: true,
        sortValue: (s) => s.agentId,
        className: "min-w-[10rem]",
        cell: (s) => {
          const Icon = s.isBot ? Bot : User;
          return (
            <div className="flex min-w-0 items-center gap-075 font-medium text-text">
              <Icon className="h-3.5 w-3.5 shrink-0 text-text-subtlest" />
              <span className="truncate">{s.agentId}</span>
            </div>
          );
        },
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">agents</span>
          </span>
        ),
      },
      {
        id: "scored",
        header: "Scored",
        sortable: true,
        sortValue: (s) => s.scored,
        align: "right",
        className: "min-w-[5rem] whitespace-nowrap",
        cell: (s) => <span className="tabular-nums text-text">{s.scored}</span>,
        footer: (visible) => (
          <span className="tabular-nums">{visible.reduce((n, s) => n + s.scored, 0)}</span>
        ),
      },
      {
        id: "avg",
        header: "Avg score",
        sortable: true,
        sortValue: (s) => s.avg,
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (s) => <ScoreBand total={s.avg} size="sm" />,
      },
      {
        id: "delta",
        header: "Δ 7d",
        sortable: true,
        sortValue: (s) => s.delta7d,
        className: "min-w-[5.5rem] whitespace-nowrap",
        cell: (s) => {
          const Trend = s.delta7d > 0.5 ? ArrowUp : s.delta7d < -0.5 ? ArrowDown : Minus;
          return (
            <span
              className={cn(
                "inline-flex items-center gap-025",
                s.delta7d > 0.5
                  ? "text-text-success-bolder"
                  : s.delta7d < -0.5
                    ? "text-text-danger-bolder"
                    : "text-text-subtlest",
              )}
            >
              <Trend className="h-3 w-3" /> {Math.abs(s.delta7d).toFixed(1)}
            </span>
          );
        },
      },
      {
        id: "weakest",
        header: "Weakest",
        sortable: true,
        sortValue: (s) => s.weakestSection,
        className: "min-w-[8rem]",
        cell: (s) => <span className="truncate text-text-subtle">{s.weakestSection}</span>,
      },
      {
        id: "coaching",
        header: "Coaching",
        sortable: true,
        sortValue: (s) => s.openCoaching,
        align: "right",
        className: "min-w-[6rem] whitespace-nowrap",
        cell: (s) =>
          s.openCoaching > 0 ? (
            <Lozenge tone="warning">{s.openCoaching} open</Lozenge>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
        footer: (visible) => {
          const open = visible.reduce((n, s) => n + s.openCoaching, 0);
          return <span className="text-body-small text-text-subtlest">{open} open</span>;
        },
      },
    ],
    [],
  );

  return (
    <RecordsTable
      rows={stats}
      getRowId={(s) => s.agentId}
      columns={columns}
      activeRowId={activeAgent}
      onRowClick={(s) => onSelect(s.agentId)}
      defaultSort={{ id: "avg", dir: -1 }}
      ariaLabel="Agent QA trends"
      tableClassName="min-w-[40rem]"
      emptyMessage="No scored agents in this window."
    />
  );
}
