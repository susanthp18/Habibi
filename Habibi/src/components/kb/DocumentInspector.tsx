import { Button } from "@/components/ui/button";
import { DOC_TYPE_LABEL, type KbChunk, type KbDocument } from "@/data/kb-seed";
import { RefreshCw, Power, PowerOff, FileUp, X } from "lucide-react";

export function DocumentInspector({
  doc,
  chunks,
  onClose,
  onReindex,
  onToggle,
  onOpenChunk,
  reindexing,
}: {
  doc: KbDocument;
  chunks: KbChunk[];
  onClose: () => void;
  onReindex: () => void;
  onToggle: () => void;
  onOpenChunk: (chunk: KbChunk) => void;
  reindexing: boolean;
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="shrink-0 border-b border-[var(--border-token)] p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
              {DOC_TYPE_LABEL[doc.type]} · {doc.version}
            </div>
            <div className="mt-0.5 truncate text-[15px] font-semibold text-brand-navy">
              {doc.title}
            </div>
            <div className="truncate text-[11px] text-text-muted">{doc.filename}</div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-text-muted hover:bg-surface-sunken"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {doc.tags.map((t) => (
            <span
              key={t}
              className="rounded-full bg-surface-sunken px-2 py-0.5 text-[10px] text-text-secondary"
            >
              #{t}
            </span>
          ))}
        </div>
        <div className="mt-3 flex gap-1.5">
          <Button size="sm" variant="outline" onClick={onReindex} disabled={reindexing}>
            <RefreshCw className={`mr-1 h-3 w-3 ${reindexing ? "animate-spin" : ""}`} />
            Re-index
          </Button>
          <Button size="sm" variant="outline" onClick={onToggle}>
            {doc.enabled ? (
              <>
                <PowerOff className="mr-1 h-3 w-3" /> Disable
              </>
            ) : (
              <>
                <Power className="mr-1 h-3 w-3" /> Enable
              </>
            )}
          </Button>
          <Button size="sm" variant="outline">
            <FileUp className="mr-1 h-3 w-3" /> New version
          </Button>
        </div>
      </div>

      <div className="grid shrink-0 grid-cols-3 gap-2 border-b border-[var(--border-token)] p-3 text-[11px]">
        <div>
          <div className="text-text-muted">Chunk size</div>
          <div className="font-medium text-brand-navy">{doc.chunkSize}</div>
        </div>
        <div>
          <div className="text-text-muted">Overlap</div>
          <div className="font-medium text-brand-navy">{doc.overlap}</div>
        </div>
        <div>
          <div className="text-text-muted">Embedding</div>
          <div className="truncate font-mono text-[10px] text-brand-navy">
            {doc.embeddingModel}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Chunks ({chunks.length})
          </div>
          <div className="text-[10px] text-text-muted">Updated by {doc.updatedBy}</div>
        </div>
        <ul className="space-y-1.5">
          {chunks.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => onOpenChunk(c)}
                className="w-full rounded-md border border-[var(--border-token)] bg-surface-app p-2 text-left transition-colors hover:border-brand-primary/40 hover:bg-brand-tint/40"
              >
                <div className="flex items-center justify-between text-[10px] text-text-muted">
                  <span className="font-mono">#{c.index}</span>
                  <span>
                    {c.tokens} tok · {c.hits} hits
                  </span>
                </div>
                <div className="mt-0.5 truncate text-[11px] font-medium text-text-secondary">
                  {c.heading}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[12px] text-text-primary">{c.text}</div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
