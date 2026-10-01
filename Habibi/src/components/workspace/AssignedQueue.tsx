import { useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronRight, Inbox, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  dueLabel,
  enactedByLabel,
  spanLabel,
  liveLevel,
  useWorkItemPages,
  useWorkspaceSummary,
  type DueFilter,
  type WorkItem,
  type WorkItemEntityType,
  type WorkspaceScope,
} from "@/api/workspace";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { Input } from "@/components/ui/input";
import { SlaPill } from "@/components/ui/SlaPill";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fmtDateTime, fmtMoney } from "@/lib/format";
import { useNow } from "@/lib/use-now";
import { useDebounced } from "@/lib/use-debounced";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";

export type QueueTab = "all" | WorkItemEntityType;

const TABS: { key: QueueTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "dispute", label: "Disputes" },
  { key: "callback", label: "Callbacks" },
  { key: "document_request", label: "Doc requests" },
  { key: "promise", label: "Promises to chase" },
  { key: "followup", label: "Follow-ups" },
  { key: "lead", label: "Leads" },
  { key: "bounce", label: "Bounces" },
];

const DUE_OPTIONS: { key: DueFilter; label: string }[] = [
  { key: "attention", label: "Needs attention" },
  { key: "overdue", label: "Overdue" },
  { key: "due_soon", label: "Due within 2h" },
  { key: "later", label: "Later" },
];

/** What the amount on a row is. One "Amount" column meant five things. */
function amountQualifier(row: WorkItem): string {
  switch (row.entityType) {
    case "dispute":
      return "Disputed";
    case "promise":
      return row.status === "partial" ? "Remaining" : "Promised";
    case "lead":
      return "Offer";
    case "bounce":
      return "Bounced";
    default:
      return "";
  }
}

export function AssignedQueue({
  scope,
  onScope,
  tab,
  onTab,
  due,
  onDue,
}: {
  scope: WorkspaceScope;
  onScope: (scope: WorkspaceScope) => void;
  tab: QueueTab;
  onTab: (tab: QueueTab) => void;
  due: DueFilter | undefined;
  onDue: (due: DueFilter | undefined) => void;
}) {
  const navigate = useNavigate();
  const now = useNow();
  const [search, setSearch] = useState("");
  const summary = useWorkspaceSummary(scope);
  const counts = summary.data?.queueCounts;
  const totals = summary.data?.scopeTotals;

  // Search on the server, after the operator pauses typing.
  const q = useDebounced(search);

  const items = useWorkItemPages({
    scope,
    entityType: tab === "all" ? undefined : tab,
    due,
    q,
  });
  const rows = useMemo(() => items.data?.pages.flat() ?? [], [items.data]);
  const filtered = Boolean(due || q.trim());
  const tabLabel = TABS.find((t) => t.key === tab)?.label ?? "All";

  // Sorting by another column reorders only the rows loaded so far, so it is
  // offered once the whole queue is loaded; until then the server's deadline
  // order is the only honest one.
  const allLoaded = !items.hasNextPage;
  const columns = useMemo<RecordsColumn<WorkItem>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        sticky: true,
        sortable: allLoaded,
        sortValue: (row) => row.customer,
        className: "min-w-[12rem]",
        cell: (row) => (
          <div className="flex min-w-0 items-center gap-100">
            <RecordsAvatarMark label={row.customer || "?"} />
            <span className="min-w-0">
              {row.customerId ? (
                <Link
                  to="/customers/$customerId"
                  params={{ customerId: row.customerId }}
                  className="block truncate text-body font-medium text-text hover:text-text-brand hover:underline"
                >
                  {row.customer}
                </Link>
              ) : (
                <span className="block truncate text-body font-medium text-text">
                  {row.customer}
                </span>
              )}
              <span className="block truncate text-body-small text-text-subtlest">
                {row.accountId || "—"}
              </span>
            </span>
          </div>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">shown</span>
          </span>
        ),
      },
      {
        id: "task",
        header: "Task",
        sortable: allLoaded,
        sortValue: (row) => row.type,
        className: "min-w-[18rem]",
        cell: (row) => (
          <button
            type="button"
            onClick={() => navigateWorkItem(navigate, row)}
            className="block min-w-0 max-w-[26rem] text-left"
          >
            <span className="flex items-center gap-075">
              <span className="truncate text-body font-medium text-text-brand hover:underline">
                {row.type}
              </span>
              {enactedByLabel(row.enactedBy) ? (
                <span className="shrink-0 rounded-medium bg-surface-sunken px-075 py-025 text-body-small text-text-subtlest">
                  {enactedByLabel(row.enactedBy)}
                </span>
              ) : null}
            </span>
            <span className="line-clamp-1 text-body-small text-text-subtle" title={row.detail}>
              {row.detail}
            </span>
          </button>
        ),
      },
      {
        id: "amount",
        header: "Amount",
        sortable: allLoaded,
        sortValue: (row) => row.amount ?? -1,
        align: "right",
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (row) =>
          typeof row.amount === "number" ? (
            <span className="text-right">
              <span className="block text-body font-medium tabular-nums text-text">
                {fmtMoney(row.amount)}
              </span>
              <span className="block text-body-small text-text-subtlest">
                {amountQualifier(row)}
              </span>
            </span>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
      },
      {
        id: "due",
        header: "Due",
        sortable: true,
        // The deadline itself, not a severity rank; undated work sorts last.
        sortValue: (row) => (row.dueAt ? new Date(row.dueAt).getTime() : Number.MAX_SAFE_INTEGER),
        className: "min-w-[9rem] whitespace-nowrap",
        cell: (row) => (
          <span title={row.dueAt ? `Due ${fmtDateTime(row.dueAt)} IST` : undefined}>
            <SlaPill
              level={liveLevel(row, now)}
              label={row.dueAt ? dueLabel(row.dueAt, now) : row.slaLabel}
            />
          </span>
        ),
        footer: (visible) => (
          <span className="text-body-small text-text-subtlest">
            {visible.filter((r) => r.dueAt && new Date(r.dueAt).getTime() < now).length} overdue
          </span>
        ),
      },
      {
        id: "created",
        header: "Created",
        sortable: allLoaded,
        sortValue: (row) => (row.createdAt ? new Date(row.createdAt).getTime() : 0),
        className: "min-w-[6rem] whitespace-nowrap",
        cell: (row) =>
          row.createdAt ? (
            <span
              className="text-body tabular-nums text-text-subtle"
              title={`${fmtDateTime(row.createdAt)} IST`}
            >
              {spanLabel(
                Math.max(0, Math.round((now - new Date(row.createdAt).getTime()) / 60_000)),
              )}{" "}
              ago
            </span>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
      },
      {
        id: "open",
        header: <span className="sr-only">Open</span>,
        align: "right",
        className: "w-[5rem] whitespace-nowrap",
        cell: (row) => (
          <button
            type="button"
            onClick={() => navigateWorkItem(navigate, row)}
            aria-label={`Open ${row.type} for ${row.customer}`}
            className="inline-flex items-center gap-050 rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-150 py-050 text-body-small font-medium text-text-brand transition-colors hover:border-border-brand/40 hover:bg-background-brand-subtlest-hovered"
          >
            Open
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        ),
      },
    ],
    [navigate, now, allLoaded],
  );

  const scopeEmpty = scope === "me" && totals?.me === 0;

  return (
    <section className="overflow-hidden rounded-xlarge border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-150 border-b border-border px-250 py-200">
        <div>
          <h2 className="heading-xsmall text-text">{scope === "me" ? "My queue" : "Team pool"}</h2>
          <p className="mt-025 text-body-small text-text-subtle">
            {scope === "me"
              ? "Assigned to you, and unassigned work on customers you own"
              : "Unassigned work on unassigned customers — anyone on the team can pick it up"}
          </p>
        </div>
        <div
          role="group"
          aria-label="Queue scope"
          className="inline-flex rounded-medium border border-border bg-surface p-025"
        >
          {(["me", "pool"] as const).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={scope === key}
              onClick={() => onScope(key)}
              className={cn(
                "rounded-medium px-150 py-050 text-body-small font-medium",
                scope === key
                  ? "bg-background-brand-subtlest text-text-brand"
                  : "text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {key === "me" ? "Mine" : "Team pool"}
              {totals ? <span className="ml-075 tabular">{totals[key]}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => onTab(v as QueueTab)}>
        <div className="border-b border-border bg-surface-sunken/60 px-200 py-150">
          <TabsList
            aria-label="Queue categories"
            className="flex h-auto gap-075 overflow-x-auto border-0 bg-transparent"
          >
            {TABS.map((t) => {
              const n = counts
                ? t.key === "all"
                  ? counts.total
                  : counts.byType[t.key]
                : undefined;
              return (
                <TabsTrigger
                  key={t.key}
                  value={t.key}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-075 rounded-full border border-b px-150 py-075 text-body-small font-medium transition-colors",
                    tab === t.key
                      ? "border-border-brand/35 bg-surface text-text-brand"
                      : "border-transparent bg-transparent text-text-subtle hover:bg-surface/70 hover:text-text",
                  )}
                >
                  {t.label}
                  {n !== undefined ? (
                    <Badge className="font-weight-bold-token tabular bg-surface/80 text-text-subtlest">
                      {n}
                    </Badge>
                  ) : null}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </div>
      </Tabs>

      <div className="flex flex-wrap items-center gap-100 border-b border-border px-250 py-100">
        <div className="relative w-64">
          <Search className="absolute left-100 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Customer, account or item id"
            aria-label={`Search ${tabLabel}`}
            size="compact"
            className="pl-400"
          />
        </div>
        <div role="group" aria-label="Deadline" className="flex flex-wrap gap-075">
          {DUE_OPTIONS.map((o) => (
            <button
              key={o.key}
              type="button"
              aria-pressed={due === o.key}
              onClick={() => onDue(due === o.key ? undefined : o.key)}
              className={cn(
                "rounded-medium border px-150 py-050 text-body-small font-medium",
                due === o.key
                  ? "border-border-brand/30 bg-background-brand-subtlest text-text-brand"
                  : "border-transparent bg-surface-sunken text-text-subtle hover:text-text",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
        {filtered && (
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-025 text-body-small font-medium text-text-brand hover:underline"
            onClick={() => {
              setSearch("");
              onDue(undefined);
            }}
          >
            <X className="h-3 w-3" /> Clear filters on {tabLabel}
          </button>
        )}
      </div>

      <div className="min-h-[16rem] bg-surface-sunken/25 p-100">
        {/* A failed read with nothing to show is an error, even when the last
            good read was empty: "Nothing here" would be a claim. */}
        {items.isError && rows.length === 0 ? (
          <QueryErrorBanner label="the queue" error={items.error} />
        ) : !items.isPending && rows.length === 0 ? (
          <div className="flex h-full min-h-[14rem] flex-col items-center justify-center gap-150 text-center">
            <Inbox className="h-5 w-5 text-text-subtlest" />
            <div className="text-body text-text-subtle">
              {filtered
                ? "Nothing matches these filters."
                : scopeEmpty && totals && totals.pool > 0
                  ? `Nothing is assigned to you. ${totals.pool} item${totals.pool === 1 ? " is" : "s are"} in the team pool.`
                  : scope === "me"
                    ? "Nothing here. Work assigned to you, or to customers you own, appears here."
                    : "The team pool is empty."}
            </div>
            {!filtered && scopeEmpty && totals && totals.pool > 0 ? (
              <button
                type="button"
                onClick={() => onScope("pool")}
                className="text-body-small font-medium text-text-brand hover:underline"
              >
                Show the team pool
              </button>
            ) : null}
          </div>
        ) : (
          <>
            <RecordsTable
              rows={rows}
              getRowId={(row) => `${row.entityType}:${row.id}`}
              columns={columns}
              isLoading={items.isPending}
              isError={items.isError}
              error={items.error}
              updatedAt={items.dataUpdatedAt}
              defaultSort={{ id: "due", dir: 1 }}
              errorLabel="the queue"
              emptyMessage="Nothing matches these filters."
              ariaLabel={`${scope === "me" ? "My queue" : "Team pool"} — ${tabLabel}`}
              className="border-0 shadow-none"
              tableClassName="min-w-[56rem]"
            />
            {items.hasNextPage && (
              <div className="flex justify-center py-100">
                <button
                  type="button"
                  disabled={items.isFetchingNextPage}
                  onClick={() => void items.fetchNextPage()}
                  className="rounded-medium border border-border bg-surface px-150 py-075 text-body-small font-medium text-text hover:bg-surface-sunken disabled:opacity-60"
                >
                  {items.isFetchingNextPage ? "Loading…" : "Load more"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
