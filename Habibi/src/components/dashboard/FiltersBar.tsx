import { CalendarDays, ChevronDown, Download, Filter, Mail, Users2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Range, Segment, TeamFilter } from "@/api/types/dashboard";

type Props = {
  range: Range;
  segment: Segment;
  team: TeamFilter;
  onRange: (r: Range) => void;
  onSegment: (s: Segment) => void;
  onTeam: (t: TeamFilter) => void;
  onDownloadCsv: () => void;
  onEmailReport: () => void;
  emailPending?: boolean;
};

const rangeOptions: { value: Range; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "qtd", label: "Quarter to date" },
];

export function FiltersBar({
  range,
  segment,
  team,
  onRange,
  onSegment,
  onTeam,
  onDownloadCsv,
  onEmailReport,
  emailPending,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-100 border-b border-border bg-surface px-300 py-150">
      <div className="mr-auto">
        <h1 className="heading-medium font-semibold text-text">Executive dashboard</h1>
        <p className="text-xs text-text-subtle">Portfolio health at a glance</p>
      </div>

      <Select value={range} onValueChange={(v) => onRange(v as Range)}>
        <SelectTrigger
          size="compact"
          className="w-[10.625rem]"
          icon={<CalendarDays />}
          aria-label="Date range"
        >
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

      <Select value={segment} onValueChange={(v) => onSegment(v as Segment)}>
        <SelectTrigger
          size="compact"
          className="w-[11.875rem]"
          icon={<Filter />}
          aria-label="Portfolio"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All portfolios</SelectItem>
          <SelectItem value="card">Credit Card</SelectItem>
          <SelectItem value="personal">Personal Loan</SelectItem>
          <SelectItem value="auto">Auto Loan</SelectItem>
        </SelectContent>
      </Select>

      <Select value={team} onValueChange={(v) => onTeam(v as TeamFilter)}>
        <SelectTrigger
          size="compact"
          className="w-[9.375rem]"
          icon={<Users2 />}
          aria-label="Handling"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All handling</SelectItem>
          <SelectItem value="bot">Bot only</SelectItem>
          <SelectItem value="human">Human only</SelectItem>
        </SelectContent>
      </Select>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="h-400 gap-075">
            <Download className="h-3.5 w-3.5" />
            Export
            <ChevronDown className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuItem onSelect={onDownloadCsv}>
            <Download className="h-3.5 w-3.5" />
            <div>
              <div className="font-medium">Download CSV</div>
              <div className="text-body-small text-text-subtlest">The lists on this screen, now</div>
            </div>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onEmailReport} disabled={emailPending}>
            <Mail className="h-3.5 w-3.5" />
            <div>
              <div className="font-medium">Email me</div>
              <div className="text-body-small text-text-subtlest">A link to the full CSV</div>
            </div>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
