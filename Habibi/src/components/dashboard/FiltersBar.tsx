import { CalendarDays, Download, Filter, Users2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Range, Segment, TeamFilter } from "@/data/dashboard-seed";

type Props = {
  range: Range;
  segment: Segment;
  team: TeamFilter;
  onRange: (r: Range) => void;
  onSegment: (s: Segment) => void;
  onTeam: (t: TeamFilter) => void;
  onExport: () => void;
};

const rangeOptions: { value: Range; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "qtd", label: "Quarter to date" },
];

export function FiltersBar({ range, segment, team, onRange, onSegment, onTeam, onExport }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-100 border-b border-border bg-surface px-300 py-150">
      <div className="mr-auto">
        <h1 className="heading-medium font-semibold text-text">Executive dashboard</h1>
        <p className="text-xs text-text-subtle">Portfolio health at a glance</p>
      </div>

      <div className="flex items-center gap-075 rounded-medium border border-border bg-surface px-100 py-050">
        <CalendarDays className="h-3.5 w-3.5 text-text-subtle" />
        <Select value={range} onValueChange={(v) => onRange(v as Range)}>
          <SelectTrigger className="h-7 w-[9.375rem] border-0 shadow-none focus:ring-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {rangeOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-075 rounded-medium border border-border bg-surface px-100 py-050">
        <Filter className="h-3.5 w-3.5 text-text-subtle" />
        <Select value={segment} onValueChange={(v) => onSegment(v as Segment)}>
          <SelectTrigger className="h-7 w-[10.625rem] border-0 shadow-none focus:ring-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All portfolios</SelectItem>
            <SelectItem value="card">Credit Card</SelectItem>
            <SelectItem value="personal">Personal Loan</SelectItem>
            <SelectItem value="auto">Auto Loan</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-075 rounded-medium border border-border bg-surface px-100 py-050">
        <Users2 className="h-3.5 w-3.5 text-text-subtle" />
        <Select value={team} onValueChange={(v) => onTeam(v as TeamFilter)}>
          <SelectTrigger className="h-7 w-[8.125rem] border-0 shadow-none focus:ring-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All handling</SelectItem>
            <SelectItem value="bot">Bot only</SelectItem>
            <SelectItem value="human">Human only</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Button variant="outline" size="sm" onClick={onExport} className="h-9 gap-075">
        <Download className="h-3.5 w-3.5" />
        Export
      </Button>
    </div>
  );
}
