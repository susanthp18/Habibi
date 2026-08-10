import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { AlertTriangle, ChevronRight, Filter, Inbox, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { bucketWorkItems, useWorkItems, type WorkItem } from "@/api/workspace";
import { type QueueRow, type SlaLevel } from "@/data/workspace-seed";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { SlaPill } from "@/components/ui/SlaPill";
import { Badge } from "@/components/ui/badge";

type TabKey = "disputes" | "callbacks" | "docs" | "ptps" | "followups";

const TAB_META: { key: TabKey; label: string }[] = [
  { key: "disputes", label: "Disputes" },
  { key: "callbacks", label: "Callbacks" },
  { key: "docs", label: "Doc requests" },
  { key: "ptps", label: "Broken PTPs" },
  { key: "followups", label: "Followups" },
];

const SLA_OPTIONS: SlaLevel[] = ["ok", "warn", "breach"];

/** Fixed list viewport (~6–7 rows). Same height on every chip so Disputes(3)
 *  vs Callbacks(7) doesn't jump the page layout or leave a stretched void. */
const QUEUE_VIEWPORT = "h-[22.5rem]";

// Filter *buttons*, not status chips — these stay hand-styled on purpose. A Lozenge is a
// status readout; wearing one as a toggle would fight the button's own padding and hit area.
const slaChipIdle = "bg-surface-sunken text-text-subtle border border-transparent";
const slaChipActive: Record<SlaLevel, string> = {
  ok: "border-border-success/25 bg-background-success text-text-success",
  warn: "border-border-warning/35 bg-background-warning text-text-warning",
  breach: "border-border-danger/30 bg-background-danger text-text-danger",
};

export function AssignedQueue() {
  const navigate = useNavigate();
  const { data: items, isLoading, isError, refetch } = useWorkItems("me");
  const [active, setActive] = useState<TabKey>("disputes");
  const [q, setQ] = useState("");
  const [slaFilter, setSlaFilter] = useState<Set<SlaLevel>>(new Set());
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Rows animate on first mount only. Without this gate, refetches (15s stale
  // time), filter changes and tab switches re-trigger the stagger on every row.
  const [animateRows, setAnimateRows] = useState(true);
  useEffect(() => {
    const t = window.setTimeout(() => setAnimateRows(false), 600);
    return () => window.clearTimeout(t);
  }, []);

  const buckets = useMemo(() => bucketWorkItems(items ?? []), [items]);

  const tabs: { key: TabKey; label: string; rows: WorkItem[] }[] = TAB_META.map((t) => ({
    ...t,
    rows: buckets[t.key] as WorkItem[],
  }));

  const current = tabs.find((t) => t.key === active) ?? tabs[0]!;

  // Empty tabs stay hidden (they only add noise — e.g. "Followups: 0"), unless
  // the user is currently viewing that tab.
  const visibleTabs = tabs.filter((t) => t.key === active || t.rows.length > 0);

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
    <section className="overflow-hidden rounded-xlarge border border-border bg-surface">
      <div className="flex items-center justify-between gap-150 border-b border-border px-250 py-200">
        <div>
          <h2 className="heading-xsmall text-text">My assigned queue</h2>
          <p className="mt-025 text-body-small text-text-subtle">
            Items routed to you across channels
          </p>
        </div>
        <Popover open={filtersOpen} onOpenChange={setFiltersOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-075 rounded-medium border px-150 py-075 text-body-small font-medium transition-colors",
                filterActive
                  ? "border-border-brand/30 bg-background-brand-subtlest text-text-brand"
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken hover:text-text",
              )}
            >
              <Filter className="h-3.5 w-3.5" />
              Filters
              {filterActive && (
                <span className="rounded-medium bg-surface/80 px-075 py-025 text-body-small font-weight-bold-token text-text-brand">
                  on
                </span>
              )}
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 space-y-150 p-150">
            <div className="flex items-center justify-between">
              <span className="text-body-small font-weight-bold-token text-text">Filter queue</span>
              {filterActive && (
                <button
                  type="button"
                  className="text-body-small text-text-subtlest hover:text-text"
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
              <Search className="absolute left-100 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Customer, account, id…"
                className="h-400 pl-400 text-body-small"
              />
            </div>
            <div>
              <div className="mb-075 text-body-small font-medium text-text-subtlest">
                SLA
              </div>
              <div className="flex flex-wrap gap-075">
                {SLA_OPTIONS.map((level) => (
                  <button
                    key={level}
                    type="button"
                    onClick={() => toggleSla(level)}
                    className={cn(
                      "rounded-medium border px-150 py-050 text-body-small font-medium capitalize",
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
      <div className="border-b border-border bg-surface-sunken/60 px-200 py-150">
        <div className="flex gap-075 overflow-x-auto" role="tablist" aria-label="Queue tabs">
          {visibleTabs.map((t) => {
            const isActive = active === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={isActive}
                id={`queue-tab-${t.key}`}
                aria-controls="queue-tabpanel"
                onClick={() => setActive(t.key)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-075 rounded-full border px-150 py-075 text-body-small font-medium transition-colors",
                  isActive
                    ? "border-border-brand/35 bg-surface text-text-brand"
                    : "border-transparent bg-transparent text-text-subtle hover:bg-surface/70 hover:text-text",
                )}
              >
                {t.label}
                <Badge
                  className={cn(
                    "font-weight-bold-token tabular",
                    isActive
                      ? "bg-background-brand-subtlest text-text-brand"
                      : "bg-surface/80 text-text-subtlest",
                  )}
                >
                  {t.rows.length}
                </Badge>
              </button>
            );
          })}
        </div>
      </div>

      {filterActive && (
        <div className="flex items-center gap-100 border-b border-border bg-background-brand-subtlest/40 px-250 py-075 text-body-small text-text-subtle">
          Showing {filteredRows.length} of {current.rows.length}
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-025 font-medium text-text-brand hover:underline"
            onClick={() => {
              setQ("");
              setSlaFilter(new Set());
            }}
          >
            <X className="h-3 w-3" /> Clear filters
          </button>
        </div>
      )}

      <div
        className={cn(QUEUE_VIEWPORT, "overflow-auto overscroll-contain bg-surface-sunken/25")}
        role="tabpanel"
        id="queue-tabpanel"
        aria-labelledby={`queue-tab-${active}`}
      >
        <table className="w-full text-body tabular">
          <caption className="sr-only">
            My assigned queue — {current.label}, {filteredRows.length} item
            {filteredRows.length === 1 ? "" : "s"}
          </caption>
          <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_var(--border)]">
            <tr className="border-b-2 border-border text-left text-body-small font-weight-bold-token text-text-subtlest">
              <th className="px-250 py-150">Customer</th>
              <th className="px-150 py-150">Type</th>
              <th className="px-150 py-150">Detail</th>
              <th className="px-150 py-150 text-right">Amount</th>
              <th className="px-150 py-150">SLA</th>
              <th className="px-150 py-150">Age</th>
              <th className="px-250 py-150" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <>
                {Array.from({ length: 4 }).map((_, i) => (
                  <tr key={`queue-skeleton-${i}`} className="border-t border-border bg-surface">
                    <td className="px-250 py-150">
                      <Skeleton className="h-4 w-36" />
                      <Skeleton className="mt-075 h-3 w-24" />
                    </td>
                    <td className="px-150 py-150">
                      <Skeleton className="h-4 w-16" />
                    </td>
                    <td className="px-150 py-150">
                      <Skeleton className="h-4 w-64 max-w-full" />
                    </td>
                    <td className="px-150 py-150">
                      <Skeleton className="ml-auto h-4 w-20" />
                    </td>
                    <td className="px-150 py-150">
                      <Skeleton className="h-4 w-20" />
                    </td>
                    <td className="px-150 py-150">
                      <Skeleton className="h-4 w-10" />
                    </td>
                    <td className="px-250 py-150">
                      <Skeleton className="ml-auto h-6 w-16" />
                    </td>
                  </tr>
                ))}
              </>
            )}
            {isError && !isLoading && (
              <tr className="bg-surface">
                <td colSpan={7} className="px-250 py-500">
                  <div className="flex flex-col items-center gap-150 text-center">
                    <AlertTriangle className="h-5 w-5 text-text-danger" />
                    <div className="text-body text-text-subtle">
                      Couldn&rsquo;t load your queue.
                    </div>
                    <button
                      type="button"
                      onClick={() => void refetch()}
                      className="rounded-medium border border-border bg-surface px-150 py-075 text-body-small font-medium text-text transition-colors hover:bg-surface-sunken"
                    >
                      Retry
                    </button>
                  </div>
                </td>
              </tr>
            )}
            {!isLoading && !isError && filteredRows.length === 0 && (
              <tr className="bg-surface">
                <td colSpan={7} className="px-250 py-500">
                  <div className="flex flex-col items-center gap-150 text-center">
                    <Inbox className="h-5 w-5 text-text-subtlest" />
                    <div className="text-body text-text-subtle">
                      {current.rows.length === 0
                        ? "Nothing in this tab right now. New items assigned to you will appear here."
                        : "No rows match your filters."}
                    </div>
                  </div>
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
                  animate={animateRows}
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
  animate,
  onOpen,
}: {
  row: QueueRow | WorkItem;
  index: number;
  animate: boolean;
  onOpen: () => void;
}) {
  const amount = row.amount;
  const hasAmount = typeof amount === "number" && Number.isFinite(amount);
  return (
    <tr
      className={cn(
        "border-t border-border bg-surface transition-colors hover:bg-background-brand-subtlest/40",
        animate && "animate-fade-up",
      )}
      style={animate ? { animationDelay: `${index * 30}ms` } : undefined}
    >
      <td className="px-250 py-150">
        <button
          type="button"
          onClick={onOpen}
          className="focus-ring rounded-small font-medium text-text transition-colors hover:text-text-brand hover:underline"
          title="Open this item"
        >
          {row.customer || "Unknown"}
        </button>
        <div className="font-mono text-body-small text-text-subtlest">{row.accountId || "—"}</div>
      </td>
      <td className="px-150 py-150 text-text">{row.type}</td>
      <td className="max-w-[13.75rem] truncate px-150 py-150 text-text-subtle" title={row.detail}>
        {row.detail}
      </td>
      <td className="px-150 py-150 text-right font-mono font-medium text-text">
        {hasAmount ? `₹${amount.toLocaleString("en-IN")}` : "—"}
      </td>
      <td className="px-150 py-150">
        <SlaPill level={row.sla} label={row.slaLabel} />
      </td>
      <td className="px-150 py-150 text-text-subtle">{row.ageHours}h</td>
      <td className="px-250 py-150 text-right">
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex items-center gap-050 rounded-medium border border-border-brand/25 bg-background-brand-subtlest/50 px-150 py-050 text-body-small font-medium text-text-brand transition-colors hover:border-border-brand/40 hover:bg-background-brand-subtlest"
        >
          Open
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  );
}
