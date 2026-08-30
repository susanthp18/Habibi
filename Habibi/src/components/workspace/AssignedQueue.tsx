import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { AlertTriangle, ChevronRight, Filter, Inbox, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { bucketWorkItems, enactedByLabel, useWorkItems, type WorkItem } from "@/api/workspace";
import { type SlaLevel } from "@/data/workspace-seed";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { SlaPill } from "@/components/ui/SlaPill";
import { Badge } from "@/components/ui/badge";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";

type TabKey = "disputes" | "callbacks" | "docs" | "ptps" | "followups" | "bounces";

const TAB_META: { key: TabKey; label: string }[] = [
  { key: "disputes", label: "Disputes" },
  { key: "callbacks", label: "Callbacks" },
  { key: "docs", label: "Doc requests" },
  { key: "ptps", label: "Broken PTPs" },
  { key: "followups", label: "Followups" },
  { key: "bounces", label: "Bounces" },
];

const SLA_OPTIONS: SlaLevel[] = ["ok", "warn", "breach"];

const slaChipIdle = "bg-surface-sunken text-text-subtle border border-transparent";
const slaChipActive: Record<SlaLevel, string> = {
  ok: "border-border-success/25 bg-background-success text-text-success",
  warn: "border-border-warning/35 bg-background-warning text-text-warning",
  breach: "border-border-danger/30 bg-background-danger text-text-danger",
};

const SLA_RANK: Record<SlaLevel, number> = { breach: 3, warn: 2, ok: 1 };

export function AssignedQueue() {
  const navigate = useNavigate();
  const { data: items, isLoading, isError, refetch } = useWorkItems("me");
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
  const visibleTabs = tabs.filter((t) => t.key === active || t.rows.length > 0);

  // Prefer a non-empty tab on first load when disputes is empty.
  useEffect(() => {
    if (!items?.length) return;
    if ((buckets[active] as WorkItem[] | undefined)?.length) return;
    const first = TAB_META.find((t) => (buckets[t.key] as WorkItem[]).length > 0);
    if (first) setActive(first.key);
  }, [items, buckets, active]);

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

  const columns = useMemo<RecordsColumn<WorkItem>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        sticky: true,
        sortable: true,
        sortValue: (row) => row.customer,
        className: "min-w-[13rem]",
        cell: (row) => (
          <button
            type="button"
            onClick={() => navigateWorkItem(navigate, row)}
            className="flex min-w-0 items-center gap-100 text-left"
          >
            <RecordsAvatarMark label={row.customer || "?"} />
            <span className="min-w-0">
              <span className="block truncate text-body font-medium text-text-brand hover:underline">
                {row.customer || "Unknown"}
              </span>
              <span className="block truncate text-body-small text-text-subtlest">
                {row.accountId || "—"}
              </span>
            </span>
          </button>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">items</span>
          </span>
        ),
      },
      {
        id: "type",
        header: "Type",
        sortable: true,
        sortValue: (row) => row.type,
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (row) => (
          <span className="inline-flex items-center gap-075">
            <span className="text-body text-text">{row.type}</span>
            {enactedByLabel(row.enactedBy) ? (
              <span className="rounded-medium bg-surface-sunken px-075 py-025 text-body-small text-text-subtlest">
                {enactedByLabel(row.enactedBy)}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        id: "detail",
        header: "Detail",
        className: "min-w-[22rem]",
        cell: (row) => (
          <span className="line-clamp-2 text-body text-text-subtle" title={row.detail}>
            {row.detail}
          </span>
        ),
      },
      {
        id: "amount",
        header: "Amount",
        sortable: true,
        sortValue: (row) => (typeof row.amount === "number" ? row.amount : -1),
        align: "right",
        className: "min-w-[7rem] whitespace-nowrap",
        headerClassName: "min-w-[7rem]",
        cell: (row) => {
          const amount = row.amount;
          const hasAmount = typeof amount === "number" && Number.isFinite(amount);
          return (
            <span className="text-body font-medium tabular-nums text-text">
              {hasAmount ? `₹${amount.toLocaleString("en-IN")}` : "—"}
            </span>
          );
        },
        footer: (visible) => {
          const sum = visible.reduce(
            (s, r) =>
              s + (typeof r.amount === "number" && Number.isFinite(r.amount) ? r.amount : 0),
            0,
          );
          return sum > 0 ? (
            <span className="text-body-small font-semibold tabular-nums text-text">
              ₹{sum.toLocaleString("en-IN")}
            </span>
          ) : (
            <span className="text-text-subtlest">—</span>
          );
        },
      },
      {
        id: "sla",
        header: "SLA",
        sortable: true,
        sortValue: (row) => SLA_RANK[row.sla] ?? 0,
        className: "min-w-[9rem] whitespace-nowrap",
        cell: (row) => <SlaPill level={row.sla} label={row.slaLabel} />,
        footer: (visible) => {
          const breach = visible.filter((r) => r.sla === "breach").length;
          return <span className="text-body-small text-text-subtlest">{breach} breach</span>;
        },
      },
      {
        id: "age",
        header: "Age",
        sortable: true,
        sortValue: (row) => row.ageHours ?? 0,
        className: "min-w-[4.5rem] whitespace-nowrap",
        cell: (row) => (
          <span className="text-body tabular-nums text-text-subtle">{row.ageHours}h</span>
        ),
      },
      {
        id: "open",
        header: "Open",
        align: "right",
        className: "min-w-[5.5rem] whitespace-nowrap",
        cell: (row) => (
          <button
            type="button"
            onClick={() => navigateWorkItem(navigate, row)}
            className="inline-flex items-center gap-050 rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-150 py-050 text-body-small font-medium text-text-brand transition-colors hover:border-border-brand/40 hover:bg-background-brand-subtlest-hovered"
          >
            Open
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        ),
      },
    ],
    [navigate],
  );

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
              <div className="mb-075 text-body-small font-medium text-text-subtlest">SLA</div>
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
        className="min-h-[16rem] overflow-hidden bg-surface-sunken/25 p-100"
        role="tabpanel"
        id="queue-tabpanel"
        aria-labelledby={`queue-tab-${active}`}
      >
        {isError && !isLoading ? (
          <div className="flex h-full flex-col items-center justify-center gap-150 text-center">
            <AlertTriangle className="h-5 w-5 text-text-danger" />
            <div className="text-body text-text-subtle">Couldn&rsquo;t load your queue.</div>
            <button
              type="button"
              onClick={() => void refetch()}
              className="rounded-medium border border-border bg-surface px-150 py-075 text-body-small font-medium text-text transition-colors hover:bg-surface-sunken"
            >
              Retry
            </button>
          </div>
        ) : !isLoading && filteredRows.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-150 text-center">
            <Inbox className="h-5 w-5 text-text-subtlest" />
            <div className="text-body text-text-subtle">
              {current.rows.length === 0
                ? "Nothing in this tab right now. New items assigned to you will appear here."
                : "No rows match your filters."}
            </div>
          </div>
        ) : (
          <RecordsTable
            rows={filteredRows}
            getRowId={(row) => row.id}
            columns={columns}
            isLoading={isLoading}
            emptyMessage="No rows match your filters."
            ariaLabel={`My assigned queue — ${current.label}`}
            defaultSort={{ id: "sla", dir: -1 }}
            className="h-full border-0 shadow-none"
            tableClassName="min-w-[72rem]"
          />
        )}
      </div>
    </section>
  );
}
