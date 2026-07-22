import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  STATUS_LABELS,
  STATUS_ORDER,
  type Filters,
  type PromiseStatus,
} from "@/data/promises-seed";

interface Props {
  filters: Filters;
  onChange: (patch: Partial<Filters>) => void;
  owners: string[];
  counts: Record<PromiseStatus | "all", number>;
}

export function FiltersBar({ filters, onChange, owners, counts }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border-token)] bg-surface-card px-3 py-2">
      <div className="flex items-center gap-1">
        <StatusChip
          active={filters.status === "all"}
          onClick={() => onChange({ status: "all" })}
          label={`All · ${counts.all}`}
        />
        {STATUS_ORDER.map((s) => (
          <StatusChip
            key={s}
            active={filters.status === s}
            onClick={() => onChange({ status: s })}
            label={`${STATUS_LABELS[s]} · ${counts[s]}`}
            tone={s}
          />
        ))}
      </div>

      <div className="mx-1 h-6 w-px bg-[var(--border-token)]" />

      <Select value={filters.source} onValueChange={(v) => onChange({ source: v as Filters["source"] })}>
        <SelectTrigger className="h-8 w-[130px] text-[12px]">
          <SelectValue placeholder="Source" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All sources</SelectItem>
          <SelectItem value="bot">Bot</SelectItem>
          <SelectItem value="agent">Agent</SelectItem>
          <SelectItem value="self">Self-serve</SelectItem>
        </SelectContent>
      </Select>

      <Select value={filters.aging} onValueChange={(v) => onChange({ aging: v as Filters["aging"] })}>
        <SelectTrigger className="h-8 w-[130px] text-[12px]">
          <SelectValue placeholder="Aging" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="any">Any aging</SelectItem>
          <SelectItem value="3d">Next 3 days</SelectItem>
          <SelectItem value="7d">This week</SelectItem>
          <SelectItem value="gt7">More than 7d out</SelectItem>
          <SelectItem value="overdue">Overdue</SelectItem>
        </SelectContent>
      </Select>

      <Select value={filters.amount} onValueChange={(v) => onChange({ amount: v as Filters["amount"] })}>
        <SelectTrigger className="h-8 w-[140px] text-[12px]">
          <SelectValue placeholder="Amount" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="any">Any amount</SelectItem>
          <SelectItem value="lt5">Under ₹5,000</SelectItem>
          <SelectItem value="5to25">₹5,000 – ₹25,000</SelectItem>
          <SelectItem value="gt25">Over ₹25,000</SelectItem>
        </SelectContent>
      </Select>

      <Select value={filters.owner} onValueChange={(v) => onChange({ owner: v })}>
        <SelectTrigger className="h-8 w-[140px] text-[12px]">
          <SelectValue placeholder="Owner" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All owners</SelectItem>
          {owners.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="relative ml-auto min-w-[200px] flex-1 md:max-w-xs">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
        <Input
          placeholder="Search customer, account, PTP id"
          value={filters.search}
          onChange={(e) => onChange({ search: e.target.value })}
          className="h-8 pl-8 text-[12px]"
        />
      </div>
    </div>
  );
}

function StatusChip({
  active,
  onClick,
  label,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  tone?: PromiseStatus;
}) {
  const toneRing = tone
    ? {
        upcoming: "ring-brand-primary/30",
        due_today: "ring-amber-400/40",
        kept: "ring-emerald-400/40",
        broken: "ring-red-400/40",
        partial: "ring-orange-400/40",
      }[tone]
    : "ring-brand-primary/30";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-[12px] font-medium transition-colors",
        active
          ? `bg-brand-tint text-brand-primary-dark ring-1 ${toneRing}`
          : "text-text-secondary hover:bg-surface-sunken",
      )}
    >
      {label}
    </button>
  );
}
