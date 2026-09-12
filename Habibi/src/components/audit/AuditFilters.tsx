import { Search, Download, Filter } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AuditFilterState, CallRecord } from "@/api/types/audit";
import { DISPOSITIONS, listAgents } from "@/lib/audit";

interface Props {
  calls: CallRecord[];
  filters: AuditFilterState;
  onChange: (f: AuditFilterState) => void;
  resultCount: number;
  selectedCount: number;
  onExport: () => void;
}

export function AuditFilters({
  calls,
  filters,
  onChange,
  resultCount,
  selectedCount,
  onExport,
}: Props) {
  const set = <K extends keyof AuditFilterState>(k: K, v: AuditFilterState[K]) =>
    onChange({ ...filters, [k]: v });
  const agents = listAgents(calls);

  return (
    <div className="shrink-0 border-b border-border bg-surface">
      <div className="flex flex-wrap items-center gap-100 px-200 py-150">
        <div className="relative min-w-[15rem] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtlest" />
          <Input
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Search customer, phone, call ID, or transcript…"
            className="pl-400"
          />
        </div>

        <Select
          value={filters.dateRange}
          onValueChange={(v) => set("dateRange", v as AuditFilterState["dateRange"])}
        >
          <SelectTrigger size="compact" className="w-[8.125rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="today">Today</SelectItem>
            <SelectItem value="7d">Last 7 days</SelectItem>
            <SelectItem value="30d">Last 30 days</SelectItem>
            <SelectItem value="all">All time</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={filters.channel}
          onValueChange={(v) => set("channel", v as AuditFilterState["channel"])}
        >
          <SelectTrigger size="compact" className="w-[8.125rem]">
            <SelectValue placeholder="Channel" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All channels</SelectItem>
            <SelectItem value="voice">Voice</SelectItem>
            <SelectItem value="whatsapp">WhatsApp</SelectItem>
            <SelectItem value="sms">SMS</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={filters.handler}
          onValueChange={(v) => set("handler", v as AuditFilterState["handler"])}
        >
          <SelectTrigger size="compact" className="w-[8.125rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Bot &amp; human</SelectItem>
            <SelectItem value="bot">Bot only</SelectItem>
            <SelectItem value="human">Human only</SelectItem>
            <SelectItem value="handoff">Handoff</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.agent} onValueChange={(v) => set("agent", v)}>
          <SelectTrigger size="compact" className="w-[9.375rem]">
            <SelectValue placeholder="Agent" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All agents</SelectItem>
            {agents.map((a) => (
              <SelectItem key={a} value={a}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filters.disposition}
          onValueChange={(v) => set("disposition", v as AuditFilterState["disposition"])}
        >
          <SelectTrigger size="compact" className="w-[11.25rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All dispositions</SelectItem>
            {DISPOSITIONS.map((d) => (
              <SelectItem key={d} value={d}>
                {d}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filters.sentiment}
          onValueChange={(v) => set("sentiment", v as AuditFilterState["sentiment"])}
        >
          <SelectTrigger size="compact" className="w-[8.125rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any sentiment</SelectItem>
            <SelectItem value="positive">Positive</SelectItem>
            <SelectItem value="neutral">Neutral</SelectItem>
            <SelectItem value="negative">Negative</SelectItem>
          </SelectContent>
        </Select>

        <label className="flex items-center gap-100 rounded-medium border border-border bg-surface-sunken px-150 py-075 text-body-small font-medium text-text-subtle">
          <Filter className="h-3.5 w-3.5" />
          Flagged only
          <Switch
            aria-label="Flagged only"
            checked={filters.flaggedOnly}
            onCheckedChange={(v) => set("flaggedOnly", v)}
          />
        </label>
      </div>

      <div className="flex items-center justify-between border-t border-border bg-surface-sunken px-200 py-075 text-body-small text-text-subtle">
        <div>
          <span className="font-semibold text-text">{resultCount}</span> calls
          {selectedCount > 0 && (
            <span className="ml-100 text-text-brand">· {selectedCount} selected</span>
          )}
        </div>
        <Button
          size="sm"
          variant={selectedCount > 0 ? "default" : "outline"}
          onClick={onExport}
          className="h-7 gap-075 text-body-small"
        >
          <Download className="h-3.5 w-3.5" />
          Export {selectedCount > 0 ? `(${selectedCount})` : "all"}
        </Button>
      </div>
    </div>
  );
}
