import { useEffect, useRef } from "react";
import { cn, formatKbDate } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { DOC_TYPE_LABEL, STATUS_LABEL, type KbDocument } from "@/data/kb-seed";
import { FileText, RefreshCw, Trash2 } from "lucide-react";

const statusStyles: Record<string, string> = {
  indexed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  indexing: "bg-brand-tint text-brand-primary-dark border-brand-primary/30",
  stale: "bg-amber-50 text-amber-700 border-amber-200",
  failed: "bg-red-50 text-red-700 border-red-200",
  draft: "bg-surface-sunken text-text-secondary border-[var(--border-token)]",
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
}) {
  const selectedRowRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    if (!selectedId || filteredOutSelected) return;
    selectedRowRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId, filteredOutSelected, docs]);

  if (loading) {
    return (
      <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
        <div className="space-y-0 divide-y divide-[var(--border-token)] p-0">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-3">
              <div className="h-4 w-4 animate-pulse rounded bg-surface-sunken" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3.5 w-2/5 animate-pulse rounded bg-surface-sunken" />
                <div className="h-3 w-1/4 animate-pulse rounded bg-surface-sunken" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (docs.length === 0) {
    return (
      <div className="flex min-h-[220px] flex-col items-center justify-center rounded-lg border border-dashed border-[var(--border-token)] bg-surface-card px-6 py-10 text-center">
        <FileText className="mb-2 h-8 w-8 text-text-muted" />
        <p className="text-[13px] font-medium text-brand-navy">
          {filteredOutSelected ? "No matches in this view" : "No documents yet"}
        </p>
        <p className="mt-1 max-w-sm text-[12px] text-text-muted">
          {filteredOutSelected
            ? "Clear the search to see all documents, or pick another filter."
            : "Sync from source_db to load the HDFC insurance corpus, or upload a document."}
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      {filteredOutSelected && (
        <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          Selected document is hidden by the current search. Clear search to locate it in the list.
        </div>
      )}
      <div className="max-h-[min(70vh,720px)] overflow-auto">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 z-10 bg-surface-sunken text-[11px] font-medium uppercase tracking-wide text-text-muted shadow-[0_1px_0_var(--border-token)]">
            <tr>
              <th className="px-3 py-2 text-left">Document</th>
              <th className="px-3 py-2 text-left">Type</th>
              <th className="px-2 py-2 text-left">Ver</th>
              <th className="px-2 py-2 text-right">Chunks</th>
              <th className="px-3 py-2 text-left">Status</th>
              <th className="px-3 py-2 text-left">Last indexed</th>
              <th className="px-3 py-2 text-center">Enabled</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => {
              const active = d.id === selectedId;
              const busy = reindexing.has(d.id) || deletingId === d.id;
              return (
                <tr
                  key={d.id}
                  ref={active ? selectedRowRef : undefined}
                  data-selected={active ? "true" : undefined}
                  onClick={() => onSelect(d.id)}
                  className={cn(
                    "cursor-pointer border-t border-[var(--border-token)] hover:bg-surface-sunken/60",
                    active && "bg-brand-tint/60 ring-1 ring-inset ring-brand-primary/35",
                  )}
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <FileText
                        className={cn("h-4 w-4 shrink-0", active ? "text-brand-primary" : "text-text-muted")}
                      />
                      <div className="min-w-0">
                        <div className="truncate font-medium text-brand-navy">{d.title}</div>
                        <div className="truncate text-[11px] text-text-muted">{d.filename}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-text-secondary">{DOC_TYPE_LABEL[d.type]}</td>
                  <td className="px-2 py-2.5 font-mono text-[12px] text-text-secondary">{d.version}</td>
                  <td className="px-2 py-2.5 text-right tabular-nums text-text-secondary">{d.chunks}</td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                        statusStyles[busy ? "indexing" : d.status],
                      )}
                    >
                      {busy && <RefreshCw className="mr-1 h-3 w-3 animate-spin" />}
                      {STATUS_LABEL[busy ? "indexing" : d.status]}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-[12px] text-text-secondary">
                    {formatKbDate(d.lastIndexed)}
                  </td>
                  <td className="px-3 py-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                    <Switch
                      checked={d.enabled}
                      disabled={busy}
                      onCheckedChange={(v) => onToggle(d.id, v)}
                    />
                  </td>
                  <td className="px-2 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="inline-flex items-center gap-0.5">
                      <button
                        type="button"
                        onClick={() => onReindex(d.id)}
                        disabled={busy}
                        className="rounded-md p-1.5 text-text-muted hover:bg-surface-sunken hover:text-brand-primary disabled:opacity-40"
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
                          className="rounded-md p-1.5 text-text-muted hover:bg-red-50 hover:text-red-700 disabled:opacity-40"
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
