import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type RecordsSortDir = 1 | -1;

export type RecordsColumn<T> = {
  id: string;
  header: ReactNode;
  headerIcon?: ReactNode;
  /** Stick as the leftmost identity column (after optional checkbox). */
  sticky?: boolean;
  sortable?: boolean;
  sortValue?: (row: T) => string | number | null | undefined;
  align?: "left" | "right" | "center";
  className?: string;
  headerClassName?: string;
  cell: (row: T) => ReactNode;
  footer?: (rows: T[]) => ReactNode;
};

export type RecordsTableProps<T> = {
  rows: T[];
  getRowId: (row: T) => string;
  columns: RecordsColumn<T>[];
  selectable?: boolean;
  selected?: Set<string>;
  onSelectedChange?: (next: Set<string>) => void;
  isLoading?: boolean;
  emptyMessage?: string;
  ariaLabel?: string;
  defaultSort?: { id: string; dir: RecordsSortDir };
  dense?: boolean;
  className?: string;
  /** Override table min-width (default wide CRM grid). Use min-w-full in narrow panels. */
  tableClassName?: string;
  /** Highlight a single active row (inspector / drawer selection). */
  activeRowId?: string | null;
  /** Click anywhere on the row. Action controls should stopPropagation. */
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
};

function alignClass(align: RecordsColumn<unknown>["align"]) {
  if (align === "right") return "text-right";
  if (align === "center") return "text-center";
  return "text-left";
}

export function RecordsTable<T>({
  rows,
  getRowId,
  columns,
  selectable = false,
  selected: selectedProp,
  onSelectedChange,
  isLoading = false,
  emptyMessage = "No records match.",
  ariaLabel = "Records table",
  defaultSort,
  className,
  tableClassName,
  activeRowId,
  onRowClick,
  rowClassName,
}: RecordsTableProps<T>) {
  const [internalSelected, setInternalSelected] = useState<Set<string>>(new Set());
  const selected = selectedProp ?? internalSelected;
  const setSelected = onSelectedChange ?? setInternalSelected;

  const [sort, setSort] = useState<{ id: string; dir: RecordsSortDir }>(
    () =>
      defaultSort ?? { id: columns.find((c) => c.sortable)?.id ?? columns[0]?.id ?? "", dir: 1 },
  );

  const visibleRows = useMemo(() => {
    const col = columns.find((c) => c.id === sort.id);
    if (!col?.sortable || !col.sortValue) return rows;
    const dir = sort.dir;
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return (
        String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" }) *
        dir
      );
    });
  }, [rows, columns, sort]);

  const allSelected =
    visibleRows.length > 0 && visibleRows.every((row) => selected.has(getRowId(row)));
  const partiallySelected = !allSelected && visibleRows.some((row) => selected.has(getRowId(row)));

  const toggleSort = (id: string) => {
    setSort((current) =>
      current.id === id ? { id, dir: (current.dir * -1) as RecordsSortDir } : { id, dir: 1 },
    );
  };

  const toggleRow = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleAll = () => {
    const next = new Set(selected);
    if (allSelected) visibleRows.forEach((row) => next.delete(getRowId(row)));
    else visibleRows.forEach((row) => next.add(getRowId(row)));
    setSelected(next);
  };

  const stickyPad = selectable ? "left-500" : "left-0";

  /** Sticky cells must stay fully opaque — translucent hover/selected paints let
   *  scrolled columns bleed through the frozen identity column. CSS in styles.css
   *  mirrors these paints so hover/selected stay solid even under stacking quirks. */
  const stickyBodyBg = (isSelected: boolean) =>
    isSelected
      ? "bg-background-selected"
      : "bg-surface group-hover/row:bg-background-brand-subtlest";

  return (
    <div
      className={cn(
        "records-shell flex min-h-0 flex-col overflow-hidden rounded-large border border-border bg-surface",
        className,
      )}
    >
      <div
        className="records-scroll min-h-0 flex-1 overflow-auto focus-visible:outline-none"
        tabIndex={0}
        aria-label={`${ariaLabel}. Scroll horizontally and vertically to view all columns and records.`}
      >
        <table
          className={cn(
            "records-table h-auto w-full min-w-[56rem] border-separate border-spacing-0 text-body",
            tableClassName,
          )}
        >
          <thead className="sticky top-0 z-30">
            <tr className="bg-surface-sunken">
              {selectable && (
                <th
                  data-sticky="true"
                  className="sticky left-0 z-40 w-500 border-b border-r border-border bg-surface-sunken px-150 py-100"
                >
                  <Checkbox
                    checked={allSelected ? true : partiallySelected ? "indeterminate" : false}
                    onCheckedChange={() => toggleAll()}
                    aria-label="Select all rows"
                  />
                </th>
              )}
              {columns.map((col) => {
                const sortable = !!col.sortable;
                const active = sort.id === col.id;
                return (
                  <th
                    key={col.id}
                    data-sticky={col.sticky ? "true" : undefined}
                    className={cn(
                      "border-b border-r border-border bg-surface-sunken px-150 py-100 text-body-small font-semibold text-text-subtle last:border-r-0",
                      alignClass(col.align),
                      col.sticky &&
                        cn(
                          "sticky z-40 bg-surface-sunken shadow-[2px_0_0_0_var(--border)]",
                          stickyPad,
                        ),
                      col.headerClassName,
                    )}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(col.id)}
                        className={cn(
                          "inline-flex max-w-full items-center gap-050 whitespace-nowrap rounded-small px-025 py-025 text-body-small font-semibold hover:bg-background-neutral-subtle-hovered hover:text-text",
                          col.align === "right" && "ml-auto",
                          col.align === "center" && "mx-auto",
                        )}
                      >
                        {col.headerIcon ? (
                          <span className="shrink-0 text-icon-subtle">{col.headerIcon}</span>
                        ) : null}
                        <span className="whitespace-nowrap">{col.header}</span>
                        <ArrowDown
                          className={cn(
                            "h-3 w-3 shrink-0 text-icon-subtlest opacity-0 transition-transform",
                            active && "opacity-100",
                            active && sort.dir === -1 && "rotate-180",
                          )}
                        />
                      </button>
                    ) : (
                      <span className="inline-flex max-w-full items-center gap-050 whitespace-nowrap text-body-small font-semibold">
                        {col.headerIcon ? (
                          <span className="shrink-0 text-icon-subtle">{col.headerIcon}</span>
                        ) : null}
                        <span className="whitespace-nowrap">{col.header}</span>
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody>
            {isLoading &&
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={`sk-${i}`}>
                  <td
                    colSpan={columns.length + (selectable ? 1 : 0)}
                    className="border-b border-border px-150 py-150"
                  >
                    <Skeleton className="h-400 w-full rounded-medium" />
                  </td>
                </tr>
              ))}

            {!isLoading &&
              visibleRows.map((row) => {
                const id = getRowId(row);
                const isSelected = selected.has(id) || id === activeRowId;
                return (
                  <tr
                    key={id}
                    data-row-id={id}
                    className={cn(
                      "group/row bg-surface transition-colors hover:bg-background-brand-subtlest",
                      isSelected && "bg-background-selected",
                      onRowClick && "cursor-pointer",
                      rowClassName?.(row),
                    )}
                    data-state={isSelected ? "selected" : undefined}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {selectable && (
                      <td
                        data-sticky="true"
                        className={cn(
                          "sticky left-0 z-20 border-b border-r border-border px-150 py-100",
                          stickyBodyBg(isSelected),
                        )}
                      >
                        <Checkbox
                          checked={selected.has(id)}
                          onCheckedChange={() => toggleRow(id)}
                          aria-label={`Select row ${id}`}
                        />
                      </td>
                    )}
                    {columns.map((col) => (
                      <td
                        key={col.id}
                        data-sticky={col.sticky ? "true" : undefined}
                        className={cn(
                          "relative z-0 border-b border-r border-border px-150 py-100 text-body text-text last:border-r-0",
                          alignClass(col.align),
                          col.sticky &&
                            cn(
                              "sticky z-20 shadow-[2px_0_0_0_var(--border)]",
                              stickyPad,
                              stickyBodyBg(isSelected),
                            ),
                          col.className,
                        )}
                      >
                        {col.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })}

            {!isLoading && visibleRows.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length + (selectable ? 1 : 0)}
                  className="px-200 py-500 text-center text-body text-text-subtlest"
                >
                  {emptyMessage}
                </td>
              </tr>
            )}
          </tbody>

          {!isLoading && rows.length > 0 && columns.some((c) => c.footer) && (
            <tfoot className="sticky bottom-0 z-30">
              <tr className="bg-surface-sunken">
                {selectable && (
                  <td
                    data-sticky="true"
                    className="sticky left-0 z-40 border-t border-r border-border bg-surface-sunken px-150 py-100"
                  />
                )}
                {columns.map((col) => (
                  <td
                    key={col.id}
                    data-sticky={col.sticky ? "true" : undefined}
                    className={cn(
                      "border-t border-r border-border bg-surface-sunken px-150 py-100 text-body-small text-text-subtle last:border-r-0",
                      alignClass(col.align),
                      col.sticky &&
                        cn(
                          "sticky z-40 bg-surface-sunken shadow-[2px_0_0_0_var(--border)]",
                          stickyPad,
                        ),
                    )}
                  >
                    {col.footer ? (
                      col.footer(visibleRows)
                    ) : (
                      <span className="text-text-subtlest">—</span>
                    )}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

/** Compact avatar mark used in sticky identity cells. */
export function RecordsAvatarMark({ label, className }: { label: string; className?: string }) {
  const initials = label
    .split(/\s+/)
    .filter(Boolean)
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <span
      className={cn(
        "flex h-400 w-400 shrink-0 items-center justify-center rounded-full bg-background-brand-subtlest text-body-small font-semibold text-text-brand",
        className,
      )}
      aria-hidden
    >
      {initials || "?"}
    </span>
  );
}
