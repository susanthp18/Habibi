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
import {
  ALL_DISPOSITIONS,
  listAgents,
  type AuditFilterState,
} from "@/data/audit-seed";

interface Props {
  filters: AuditFilterState;
  onChange: (f: AuditFilterState) => void;
  resultCount: number;
  selectedCount: number;
  onExport: () => void;
}

export function AuditFilters({
  filters,
  onChange,
  resultCount,
  selectedCount,
  onExport,
}: Props) {
  const set = <K extends keyof AuditFilterState>(k: K, v: AuditFilterState[K]) =>
    onChange({ ...filters, [k]: v });
  const agents = listAgents();

  return (
    <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <Input
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Search customer, phone, call ID, or transcript…"
            className="pl-8"
          />
        </div>

        <Select value={filters.dateRange} onValueChange={(v) => set("dateRange", v as AuditFilterState["dateRange"])}>
          <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="today">Today</SelectItem>
            <SelectItem value="7d">Last 7 days</SelectItem>
            <SelectItem value="30d">Last 30 days</SelectItem>
            <SelectItem value="all">All time</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.channel} onValueChange={(v) => set("channel", v as AuditFilterState["channel"])}>
          <SelectTrigger className="w-[130px]"><SelectValue placeholder="Channel" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All channels</SelectItem>
            <SelectItem value="voice">Voice</SelectItem>
            <SelectItem value="whatsapp">WhatsApp</SelectItem>
            <SelectItem value="sms">SMS</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.handler} onValueChange={(v) => set("handler", v as AuditFilterState["handler"])}>
          <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Bot &amp; human</SelectItem>
            <SelectItem value="bot">Bot only</SelectItem>
            <SelectItem value="human">Human only</SelectItem>
            <SelectItem value="handoff">Handoff</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.agent} onValueChange={(v) => set("agent", v)}>
          <SelectTrigger className="w-[150px]"><SelectValue placeholder="Agent" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All agents</SelectItem>
            {agents.map((a) => (
              <SelectItem key={a} value={a}>{a}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filters.disposition} onValueChange={(v) => set("disposition", v as AuditFilterState["disposition"])}>
          <SelectTrigger className="w-[180px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All dispositions</SelectItem>
            {ALL_DISPOSITIONS.map((d) => (
              <SelectItem key={d} value={d}>{d}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filters.sentiment} onValueChange={(v) => set("sentiment", v as AuditFilterState["sentiment"])}>
          <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any sentiment</SelectItem>
            <SelectItem value="positive">Positive</SelectItem>
            <SelectItem value="neutral">Neutral</SelectItem>
            <SelectItem value="negative">Negative</SelectItem>
          </SelectContent>
        </Select>

        <label className="flex items-center gap-2 rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 py-1.5 text-[12px] font-medium text-text-secondary">
          <Filter className="h-3.5 w-3.5" />
          Flagged only
          <Switch
            checked={filters.flaggedOnly}
            onCheckedChange={(v) => set("flaggedOnly", v)}
          />
        </label>
      </div>

      <div className="flex items-center justify-between border-t border-[var(--border-token)] bg-surface-sunken px-4 py-1.5 text-[12px] text-text-secondary">
        <div>
          <span className="font-semibold text-text-primary">{resultCount}</span> calls
          {selectedCount > 0 && (
            <span className="ml-2 text-brand-primary-dark">
              · {selectedCount} selected
            </span>
          )}
        </div>
        <Button
          size="sm"
          variant={selectedCount > 0 ? "default" : "outline"}
          onClick={onExport}
          className="h-7 gap-1.5 text-[12px]"
        >
          <Download className="h-3.5 w-3.5" />
          Export {selectedCount > 0 ? `(${selectedCount})` : "all"}
        </Button>
      </div>
    </div>
  );
}
