import { useEffect, useMemo } from "react";
import { cn, formatKbDate } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { DOC_TYPE_LABEL, STATUS_LABEL, type KbDocument } from "@/data/kb-seed";
import { FileText, RefreshCw, Trash2 } from "lucide-react";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

const statusStyles: Record<string, LozengeTone> = {
  indexed: "success",
  indexing: "selected",
  stale: "warning",
  failed: "danger",
  draft: "neutral",
};

const STATUS_RANK: Record<string, number> = {
  failed: 0,
  indexing: 1,
  stale: 2,
  draft: 3,
  indexed: 4,
};

export function DocumentsTable({
  docs,
  selectedId,
  onSelect,
  onToggle,
  onReindex,
  onDelete,
  reindexing,
  deletingId,
  loading = false,
  filteredOutSelected = false,
  emptyFromFilter = false,
}: {
  docs: KbDocument[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onReindex: (id: string) => void;
  onDelete?: (id: string) => void;
  reindexing: Set<string>;
  deletingId?: string | null;
  loading?: boolean;
  /** Selected doc exists but is hidden by the current search/filter. */
  filteredOutSelected?: boolean;
  /** List is empty because search/filters excluded all docs (collection may still have items). */
  emptyFromFilter?: boolean;
}) {
  useEffect(() => {
    if (!selectedId || filteredOutSelected) return;
    const el = document.querySelector(`[data-row-id="${CSS.escape(selectedId)}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId, filteredOutSelected]);

  const columns = useMemo<RecordsColumn<KbDocument>[]>(
    () => [
      {
        id: "document",
        header: "Document",
        sticky: true,
        sortable: true,
        sortValue: (d) => d.title,
        className: "min-w-[16rem]",
        cell: (d) => (
          <div className="flex min-w-0 items-center gap-100">
            <FileText
              className={cn(
                "h-4 w-4 shrink-0",
                d.id === selectedId ? "text-text-brand" : "text-text-subtlest",
              )}
            />
            <span className="min-w-0">
              <span className="block truncate text-body font-medium text-text">{d.title}</span>
              <span className="block truncate text-body-small text-text-subtlest">
                {d.filename}
              </span>
            </span>
          </div>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">docs</span>
          </span>
        ),
      },
      {
        id: "type",
        header: "Type",
        sortable: true,
        sortValue: (d) => DOC_TYPE_LABEL[d.type],
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (d) => <RecordsTag name={DOC_TYPE_LABEL[d.type]} />,
      },
      {
        id: "version",
        header: "Ver",
        sortable: true,
        sortValue: (d) => d.version,
        className: "min-w-[4rem] whitespace-nowrap",
        cell: (d) => (
          <span className="text-body-small tabular-nums text-text-subtle">{d.version}</span>
        ),
      },
      {
        id: "chunks",
        header: "Chunks",
        sortable: true,
        sortValue: (d) => d.chunks,
        align: "right",
        className: "min-w-[5rem] whitespace-nowrap",
        cell: (d) => <span className="tabular-nums text-text-subtle">{d.chunks}</span>,
        footer: (visible) => (
          <span className="tabular-nums">
            {visible.reduce((s, d) => s + d.chunks, 0).toLocaleString("en-IN")}
          </span>
        ),
      },
      {
        id: "status",
        header: "Status",
        sortable: true,
        sortValue: (d) => STATUS_RANK[d.status] ?? 0,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (d) => {
          const isReindexing = reindexing.has(d.id);
          const isDeleting = deletingId === d.id;
          const busy = isReindexing || isDeleting;
          return (
            <Lozenge
              tone={statusStyles[isDeleting ? "failed" : isReindexing ? "indexing" : d.status]}
            >
              {busy && <RefreshCw className="animate-spin" />}
              {isDeleting
                ? "Deleting…"
                : isReindexing
                  ? STATUS_LABEL.indexing
                  : STATUS_LABEL[d.status]}
            </Lozenge>
          );
        },
      },
      {
        id: "indexed",
        header: "Last indexed",
        sortable: true,
        sortValue: (d) => d.lastIndexed,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (d) => (
          <span className="text-body-small text-text-subtle">{formatKbDate(d.lastIndexed)}</span>
        ),
      },
      {
        id: "enabled",
        header: "Enabled",
        align: "center",
        className: "min-w-[5.5rem]",
        cell: (d) => {
          const busy = reindexing.has(d.id) || deletingId === d.id;
          return (
            <div onClick={(e) => e.stopPropagation()}>
              <Switch
                aria-label={`Enable ${d.title}`}
                checked={d.enabled}
                disabled={busy}
                onCheckedChange={(v) => onToggle(d.id, v)}
              />
            </div>
          );
        },
      },
      {
        id: "actions",
        header: "",
        align: "right",
        className: "min-w-[5.5rem] whitespace-nowrap",
        cell: (d) => {
          const busy = reindexing.has(d.id) || deletingId === d.id;
          return (
            <div className="inline-flex items-center gap-025" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                onClick={() => onReindex(d.id)}
                disabled={busy}
                className="rounded-medium p-075 text-text-subtlest hover:bg-surface-sunken hover:text-text-brand disabled:opacity-40"
                aria-label="Re-index"
                title="Re-index"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
              </button>
              {onDelete && (
                <button
                  type="button"
                  onClick={() => onDelete(d.id)}
                  disabled={busy}
                  className="rounded-medium p-075 text-text-subtlest hover:bg-background-danger-subtler hover:text-text-danger-bolder disabled:opacity-40"
                  aria-label="Delete"
                  title="Delete"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          );
        },
      },
    ],
    [deletingId, onDelete, onReindex, onToggle, reindexing, selectedId],
  );

  if (!loading && docs.length === 0) {
    return (
      <div className="flex h-full min-h-[13.75rem] flex-col items-center justify-center bg-surface px-300 py-500 text-center">
        <FileText className="mb-100 h-400 w-400 text-text-subtlest" />
        <p className="text-body font-medium text-text">
          {filteredOutSelected || emptyFromFilter ? "No matches in this view" : "No documents yet"}
        </p>
        <p className="mt-050 max-w-sm text-body-small text-text-subtlest">
          {filteredOutSelected || emptyFromFilter
            ? "Clear the search to see all documents, or pick another filter."
            : "Sync from source_db to load the HDFC insurance corpus, or upload a document."}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {filteredOutSelected && (
        <div className="shrink-0 border-b border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          Selected document is hidden by the current search. Clear search to locate it in the list.
        </div>
      )}
      <RecordsTable
        rows={docs}
        getRowId={(d) => d.id}
        columns={columns}
        isLoading={loading}
        activeRowId={selectedId}
        onRowClick={(d) => onSelect(d.id)}
        ariaLabel="Knowledge base documents"
        tableClassName="min-w-[56rem]"
        className="h-full rounded-none border-0"
      />
    </div>
  );
}
