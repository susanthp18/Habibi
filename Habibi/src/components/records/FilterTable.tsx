import { useMemo, useState, type ReactNode } from "react";
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

  return (
    <div className={cn("flex min-h-0 w-full flex-col gap-100", className)}>
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
                <span className="h-150 w-150 rounded-full" style={{ background: chip.dot }} aria-hidden />
              ) : null}
              {chip.label}
              <span
                className={cn(
                  "rounded-small px-050 text-[0.65625rem] tabular-nums",
                  active ? "bg-background-neutral text-text-subtle" : "text-text-subtlest",
                )}
              >
                {chip.count}
              </span>
            </button>
          );
        })}
      </div>

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

          {rows.map((row) => {
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

          {visibleCount === 0 && (
            <div className="px-150 py-500 text-center text-body-small text-text-subtlest">{emptyMessage}</div>
          )}
        </div>
      </div>
    </div>
  );
}
