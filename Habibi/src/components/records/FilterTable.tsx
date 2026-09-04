import { useMemo, useState, type ReactNode } from "react";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type FilterChip<K extends string> = {
  key: K | "all";
  label: string;
  /** CSS color for the status dot (omit for All). */
  dot?: string;
  count: number;
};

export type FilterTableColumn<T> = {
  id: string;
  header: string;
  /** CSS grid fraction, e.g. "1.3fr" */
  width: string;
  className?: string;
  cell: (row: T) => ReactNode;
};

type Props<T, K extends string> = {
  rows: T[];
  getRowId: (row: T) => string;
  /** Field used by the status chips. */
  getStatus: (row: T) => K;
  chips: FilterChip<K>[];
  columns: FilterTableColumn<T>[];
  isLoading?: boolean;
  /** Failed read. Takes the empty slot so `emptyMessage` cannot fire on a 500. */
  isError?: boolean;
  error?: unknown;
  /** Names the failed read for QueryErrorBanner — "the account ledger". */
  errorLabel?: string;
  emptyMessage?: string;
  ariaLabel?: string;
  className?: string;
  /** Controlled filter; omit for internal state. */
  filter?: K | "all";
  onFilterChange?: (next: K | "all") => void;
  defaultFilter?: K | "all";
};

/**
 * Compact status-chip filter table — animated show/hide rows.
 * Prefer this for task/queue screens (callbacks, documents); use RecordsTable
 * for wide CRM grids (customers, audit).
 */
export function FilterTable<T, K extends string>({
  rows,
  getRowId,
  getStatus,
  chips,
  columns,
  isLoading = false,
  isError = false,
  error,
  errorLabel = "rows",
  emptyMessage = "No rows match this filter.",
  ariaLabel = "Filtered table",
  className,
  filter: filterProp,
  onFilterChange,
  defaultFilter = "all",
}: Props<T, K>) {
  const [internal, setInternal] = useState<K | "all">(defaultFilter);
  const filter = filterProp ?? internal;
  const setFilter = onFilterChange ?? setInternal;

  const gridTemplate = columns.map((c) => c.width).join(" ");

  const visibleCount = useMemo(
    () => rows.filter((row) => filter === "all" || getStatus(row) === filter).length,
    [rows, filter, getStatus],
  );

  const showError = isError && !isLoading && visibleCount === 0;

  return (
    <div className={cn("flex min-h-0 w-full flex-col gap-100", className)}>
      {!isLoading && !showError ? (
        <div
          className="-mx-025 flex items-center gap-050 overflow-x-auto px-025 py-025"
          style={{ scrollbarWidth: "none" }}
          role="toolbar"
          aria-label="Status filters"
        >
          {chips.map((chip) => {
            const active = filter === chip.key;
            return (
              <button
                key={String(chip.key)}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(chip.key)}
                className={cn(
                  "flex h-400 shrink-0 items-center gap-075 rounded-full px-150 text-body-small font-medium transition-[background-color,box-shadow,color] duration-200",
                  active
                    ? "bg-surface text-text shadow-sm ring-1 ring-border"
                    : "text-text-subtle hover:bg-background-neutral-subtle-hovered hover:text-text",
                )}
              >
                {chip.dot ? (
                  <span
                    className="h-150 w-150 rounded-full"
                    style={{ background: chip.dot }}
                    aria-hidden
                  />
                ) : null}
                {chip.label}
                <span
                  className={cn(
                    "rounded-small px-050 text-body-micro tabular-nums",
                    active ? "bg-background-neutral text-text-subtle" : "text-text-subtlest",
                  )}
                >
                  {chip.count}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}

      <div
        aria-label={ariaLabel}
        className="min-h-0 flex-1 overflow-auto rounded-large border border-border bg-surface"
        role="region"
        tabIndex={0}
      >
        <div className="min-w-[36rem]">
          <div
            className="sticky top-0 z-10 grid border-b border-border bg-surface-sunken px-150 py-100 text-body-small font-semibold text-text-subtlest"
            style={{ gridTemplateColumns: gridTemplate }}
          >
            {columns.map((col) => (
              <span key={col.id} className={col.className}>
                {col.header}
              </span>
            ))}
          </div>

          {isLoading
            ? Array.from({ length: 6 }).map((_, i) => (
                <div key={`sk-${i}`} className="border-b border-border px-150 py-150">
                  <Skeleton className="h-400 w-full rounded-medium" />
                </div>
              ))
            : null}

          {showError ? (
            <div className="p-150">
              <QueryErrorBanner label={errorLabel} error={error} />
            </div>
          ) : null}

          {!isLoading &&
            !showError &&
            rows.map((row) => {
              const shown = filter === "all" || getStatus(row) === filter;
              return (
                <div
                  key={getRowId(row)}
                  className="grid transition-[grid-template-rows,opacity] duration-300"
                  style={{
                    gridTemplateRows: shown ? "1fr" : "0fr",
                    opacity: shown ? 1 : 0,
                    transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
                  }}
                  aria-hidden={!shown}
                >
                  <div className="overflow-hidden">
                    <div
                      className="grid items-center border-b border-border px-150 py-100 text-body-small transition-colors duration-100 last:border-0 hover:bg-background-neutral-subtle-hovered"
                      style={{ gridTemplateColumns: gridTemplate }}
                    >
                      {columns.map((col) => (
                        <div key={col.id} className={col.className}>
                          {col.cell(row)}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}

          {!isLoading && !showError && visibleCount === 0 && (
            <div className="px-150 py-500 text-center text-body-small text-text-subtlest">
              {emptyMessage}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
