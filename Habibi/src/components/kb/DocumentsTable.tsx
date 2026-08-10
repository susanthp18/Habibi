import { useEffect, useRef } from "react";
import { cn, formatKbDate } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { DOC_TYPE_LABEL, STATUS_LABEL, type KbDocument } from "@/data/kb-seed";
import { FileText, RefreshCw, Trash2 } from "lucide-react";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const statusStyles: Record<string, LozengeTone> = {
  indexed: "success",
  indexing: "selected",
  stale: "warning",
  failed: "danger",
  draft: "neutral",
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
  const selectedRowRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    if (!selectedId || filteredOutSelected) return;
    selectedRowRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    // `docs` deliberately omitted: the list is polled, so a new array identity
    // with identical content re-ran this and yanked the table back to the
    // selected row while the user was scrolling elsewhere.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, filteredOutSelected]);

  if (loading) {
    return (
      <div className="overflow-hidden rounded-large border border-border bg-surface">
        <div className="space-y-0 divide-y divide-border p-0">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-150 px-150 py-150">
              <div className="h-4 w-4 animate-pulse rounded bg-surface-sunken" />
              <div className="flex-1 space-y-075">
                <div className="h-3.5 w-100/5 animate-pulse rounded bg-surface-sunken" />
                <div className="h-3 w-050/4 animate-pulse rounded bg-surface-sunken" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (docs.length === 0) {
    return (
      <div className="flex min-h-[13.75rem] flex-col items-center justify-center rounded-large border border-dashed border-border bg-surface px-300 py-500 text-center">
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
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      {filteredOutSelected && (
        <div className="border-b border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          Selected document is hidden by the current search. Clear search to locate it in the list.
        </div>
      )}
      <div className="max-h-[min(70vh,45rem)] overflow-auto">
        <table className="w-full text-body">
          <thead className="sticky top-0 z-10 bg-surface-sunken text-body-small font-medium text-text-subtlest shadow-[0_1px_0_var(--border)]">
            <tr>
              <th className="px-150 py-100 text-left">Document</th>
              <th className="px-150 py-100 text-left">Type</th>
              <th className="px-100 py-100 text-left">Ver</th>
              <th className="px-100 py-100 text-right">Chunks</th>
              <th className="px-150 py-100 text-left">Status</th>
              <th className="px-150 py-100 text-left">Last indexed</th>
              <th className="px-150 py-100 text-center">Enabled</th>
              <th className="px-100 py-100" />
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => {
              const active = d.id === selectedId;
              const isReindexing = reindexing.has(d.id);
              const isDeleting = deletingId === d.id;
              const busy = isReindexing || isDeleting;
              return (
                <tr
                  key={d.id}
                  ref={active ? selectedRowRef : undefined}
                  data-selected={active ? "true" : undefined}
                  onClick={() => onSelect(d.id)}
                  className={cn(
                    "cursor-pointer border-t border-border hover:bg-surface-sunken/60",
                    active && "bg-background-brand-subtlest/60 ring-1 ring-inset ring-border-brand/35",
                  )}
                >
                  <td className="px-150 py-150">
                    <div className="flex items-center gap-100">
                      <FileText
                        className={cn("h-4 w-4 shrink-0", active ? "text-text-brand" : "text-text-subtlest")}
                      />
                      <div className="min-w-0">
                        <div className="truncate font-medium text-text">{d.title}</div>
                        <div className="truncate text-body-small text-text-subtlest">{d.filename}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-150 py-150 text-text-subtle">{DOC_TYPE_LABEL[d.type]}</td>
                  <td className="px-100 py-150 font-mono text-body-small text-text-subtle">{d.version}</td>
                  <td className="px-100 py-150 text-right tabular-nums text-text-subtle">{d.chunks}</td>
                  <td className="px-150 py-150">
                    <Lozenge
                      tone={statusStyles[isDeleting ? "failed" : isReindexing ? "indexing" : d.status]}
                    >
                      {busy && <RefreshCw className="animate-spin" />}
                      {isDeleting ? "Deleting…" : isReindexing ? STATUS_LABEL.indexing : STATUS_LABEL[d.status]}
                    </Lozenge>
                  </td>
                  <td className="px-150 py-150 text-body-small text-text-subtle">
                    {formatKbDate(d.lastIndexed)}
                  </td>
                  <td className="px-150 py-150 text-center" onClick={(e) => e.stopPropagation()}>
                    <Switch
                      checked={d.enabled}
                      disabled={busy}
                      onCheckedChange={(v) => onToggle(d.id, v)}
                    />
                  </td>
                  <td className="px-100 py-150 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="inline-flex items-center gap-025">
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
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
