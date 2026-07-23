import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ChevronRight, Filter, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { bucketWorkItems, useWorkItems, type WorkItem } from "@/api/workspace";
import { type QueueRow, type SlaLevel } from "@/data/workspace-seed";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { SlaPill } from "@/components/ui/SlaPill";

type TabKey = "disputes" | "callbacks" | "docs" | "ptps" | "followups";

const TAB_META: { key: TabKey; label: string }[] = [
  { key: "disputes", label: "Disputes" },
  { key: "callbacks", label: "Callbacks" },
  { key: "docs", label: "Doc requests" },
  { key: "ptps", label: "Broken PTPs" },
  { key: "followups", label: "Followups" },
];

const SLA_OPTIONS: SlaLevel[] = ["ok", "warn", "breach"];

const slaChipIdle = "bg-surface-sunken text-text-secondary border border-transparent";
const slaChipActive: Record<SlaLevel, string> = {
  ok: "border-success/25 bg-success-bg text-success",
  warn: "border-warning/35 bg-warning-bg text-warning",
  breach: "border-danger/30 bg-danger-bg text-danger",
};

export function AssignedQueue() {
  const navigate = useNavigate();
  const { data: items, isLoading, isError } = useWorkItems("me");
  const [active, setActive] = useState<TabKey>("disputes");
  const [q, setQ] = useState("");
  const [slaFilter, setSlaFilter] = useState<Set<SlaLevel>>(new Set());
  const [filtersOpen, setFiltersOpen] = useState(false);

  const buckets = useMemo(() => bucketWorkItems(items ?? []), [items]);

  const tabs: { key: TabKey; label: string; rows: WorkItem[] }[] = TAB_META.map((t) => ({
    ...t,
    rows: buckets[t.key] as WorkItem[],
  }));

  const current = tabs.find((t) => t.key === active) ?? tabs[0]!;

  const filteredRows = useMemo(() => {
    let rows = current.rows;
    if (slaFilter.size > 0) {
      rows = rows.filter((r) => slaFilter.has(r.sla));
    }
    const needle = q.trim().toLowerCase();
    if (needle) {
      rows = rows.filter(
        (r) =>
          r.customer.toLowerCase().includes(needle) ||
          r.accountId.toLowerCase().includes(needle) ||
          r.id.toLowerCase().includes(needle) ||
          r.detail.toLowerCase().includes(needle) ||
          r.type.toLowerCase().includes(needle),
      );
    }
    return rows;
  }, [current.rows, q, slaFilter]);

  const filterActive = q.trim().length > 0 || slaFilter.size > 0;

  const toggleSla = (level: SlaLevel) => {
    setSlaFilter((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  };

  return (
    <section className="overflow-hidden rounded-[12px] border border-[var(--border-token)] bg-surface-card shadow-card">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border-token)] px-5 py-3.5">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight text-brand-navy">My assigned queue</h2>
          <p className="mt-0.5 text-[12px] text-text-secondary">Items routed to you across channels</p>
        </div>
        <Popover open={filtersOpen} onOpenChange={setFiltersOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-medium transition-colors",
                filterActive
                  ? "border-brand-primary/30 bg-brand-tint text-brand-primary-dark"
                  : "border-[var(--border-token)] bg-white text-text-secondary hover:bg-surface-sunken hover:text-text-primary",
              )}
            >
              <Filter className="h-3.5 w-3.5" />
              Filters
              {filterActive && (
                <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-[10px] font-semibold text-brand-primary-dark">
                  on
                </span>
              )}
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 space-y-3 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-semibold text-brand-navy">Filter queue</span>
              {filterActive && (
                <button
                  type="button"
                  className="text-[11px] text-text-muted hover:text-text-primary"
                  onClick={() => {
                    setQ("");
                    setSlaFilter(new Set());
                  }}
                >
                  Clear
                </button>
              )}
            </div>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Customer, account, id…"
                className="h-8 pl-8 text-[12px]"
              />
            </div>
            <div>
              <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">SLA</div>
              <div className="flex flex-wrap gap-1.5">
                {SLA_OPTIONS.map((level) => (
                  <button
                    key={level}
                    type="button"
                    onClick={() => toggleSla(level)}
                    className={cn(
                      "rounded-md border px-2.5 py-1 text-[11px] font-semibold capitalize",
                      slaFilter.has(level) ? slaChipActive[level] : slaChipIdle,
                    )}
                  >
                    {level}
                  </button>
                ))}
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {/* Pill tabs */}
      <div className="border-b border-[var(--border-token)] bg-surface-sunken/60 px-4 py-2.5">
        <div className="flex gap-1.5 overflow-x-auto">
          {tabs.map((t) => {
            const isActive = active === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setActive(t.key)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors",
                  isActive
                    ? "border-brand-primary/35 bg-white text-brand-primary-dark shadow-sm"
                    : "border-transparent bg-transparent text-text-secondary hover:bg-white/70 hover:text-text-primary",
                )}
              >
                {t.label}
                <span
                  className={cn(
                    "inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular",
                    isActive ? "bg-brand-tint text-brand-primary-dark" : "bg-white/80 text-text-muted",
                  )}
                >
                  {t.rows.length}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {filterActive && (
        <div className="flex items-center gap-2 border-b border-[var(--border-token)] bg-brand-tint/40 px-5 py-1.5 text-[11px] text-text-secondary">
          Showing {filteredRows.length} of {current.rows.length}
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-0.5 font-medium text-brand-primary hover:underline"
            onClick={() => {
              setQ("");
              setSlaFilter(new Set());
            }}
          >
            <X className="h-3 w-3" /> Clear filters
          </button>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-[13px] tabular">
          <thead>
            <tr className="border-b border-[var(--border-token)] bg-surface-sunken/40 text-left text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
              <th className="px-5 py-2.5">Customer</th>
              <th className="px-3 py-2.5">Type</th>
              <th className="px-3 py-2.5">Detail</th>
              <th className="px-3 py-2.5 text-right">Amount</th>
              <th className="px-3 py-2.5">SLA</th>
              <th className="px-3 py-2.5">Age</th>
              <th className="px-5 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-[13px] text-text-muted">
                  Loading queue…
                </td>
              </tr>
            )}
            {isError && !isLoading && (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-[13px] text-danger">
                  Couldn’t load assigned queue.
                </td>
              </tr>
            )}
            {!isLoading && !isError && filteredRows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-[13px] text-text-muted">
                  {current.rows.length === 0 ? "Nothing in this tab right now." : "No rows match filters."}
                </td>
              </tr>
            )}
            {!isLoading &&
              !isError &&
              filteredRows.map((row, i) => (
                <QueueRowView
                  key={row.id}
                  row={row}
                  index={i}
                  onOpen={() => navigateWorkItem(navigate, row)}
                />
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function QueueRowView({
  row,
  index,
  onOpen,
}: {
  row: QueueRow | WorkItem;
  index: number;
  onOpen: () => void;
}) {
  const amount = row.amount;
  const hasAmount = typeof amount === "number" && Number.isFinite(amount);
  return (
    <tr
      className="animate-fade-up border-t border-[var(--border-token)] transition-colors hover:bg-brand-tint/40"
      style={{ animationDelay: `${index * 30}ms` }}
    >
      <td className="px-5 py-3">
        <div className="font-semibold text-text-primary">{row.customer || "Unknown"}</div>
        <div className="font-mono text-[11px] text-text-muted">{row.accountId || "—"}</div>
      </td>
      <td className="px-3 py-3 text-text-primary">{row.type}</td>
      <td className="max-w-[220px] truncate px-3 py-3 text-text-secondary" title={row.detail}>
        {row.detail}
      </td>
      <td className="px-3 py-3 text-right font-mono font-semibold text-text-primary">
        {hasAmount ? `₹${amount.toLocaleString("en-IN")}` : "—"}
      </td>
      <td className="px-3 py-3">
        <SlaPill level={row.sla} label={row.slaLabel} />
      </td>
      <td className="px-3 py-3 text-text-secondary">{row.ageHours}h</td>
      <td className="px-5 py-3 text-right">
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex items-center gap-1 rounded-md border border-brand-primary/25 bg-brand-tint/50 px-2.5 py-1 text-[12px] font-medium text-brand-primary-dark transition-colors hover:border-brand-primary/40 hover:bg-brand-tint"
        >
          Open
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  );
}
