import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { DOC_TYPE_LABEL, type KbChunk, type KbDocument } from "@/data/kb-seed";
import { KbTagEditor } from "@/components/kb/KbTagEditor";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { RefreshCw, Power, PowerOff, FileUp, X, Save, Trash2 } from "lucide-react";

export type KbDocumentMetaPatch = {
  title: string;
  tags: string[];
  chunkSize: number;
  overlap: number;
};

export function DocumentInspector({
  doc,
  chunks,
  onClose,
  onReindex,
  onToggle,
  onNewVersion,
  onDelete,
  onOpenChunk,
  onSaveMeta,
  reindexing,
  savingMeta = false,
  deleting = false,
}: {
  doc: KbDocument;
  chunks: KbChunk[];
  onClose: () => void;
  onReindex: () => void;
  onToggle: () => void;
  onNewVersion: () => void;
  onDelete: () => void | Promise<void>;
  onOpenChunk: (chunk: KbChunk) => void;
  onSaveMeta: (patch: KbDocumentMetaPatch) => void | Promise<void>;
  reindexing: boolean;
  savingMeta?: boolean;
  deleting?: boolean;
}) {
  const [title, setTitle] = useState(doc.title);
  const [tags, setTags] = useState<string[]>(doc.tags);
  const [chunkSize, setChunkSize] = useState(doc.chunkSize);
  const [overlap, setOverlap] = useState(doc.overlap);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setTitle(doc.title);
    setTags(doc.tags);
    setChunkSize(doc.chunkSize);
    setOverlap(doc.overlap);
  }, [doc.id, doc.title, doc.tags, doc.chunkSize, doc.overlap]);

  const dirty =
    title.trim() !== doc.title ||
    chunkSize !== doc.chunkSize ||
    overlap !== doc.overlap ||
    tags.join("\0") !== doc.tags.join("\0");

  const busy = savingMeta || reindexing || deleting;

  const save = async () => {
    if (!dirty || busy) return;
    const nextTitle = title.trim() || doc.title;
    const safeOverlap = Math.min(overlap, Math.max(0, chunkSize - 1));
    await Promise.resolve(
      onSaveMeta({
        title: nextTitle,
        tags,
        chunkSize,
        overlap: safeOverlap,
      }),
    );
  };

  return (
    <aside className="flex h-full max-h-[inherit] min-h-0 w-full flex-col overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="shrink-0 border-b border-[var(--border-token)] p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
              {DOC_TYPE_LABEL[doc.type]} · {doc.version}
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-wide text-text-muted">Title</Label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="mt-1 h-8 text-[14px] font-semibold"
                disabled={busy}
              />
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

        <div className="mt-3 space-y-1.5">
          <Label className="text-[10px] uppercase tracking-wide text-text-muted">Tags</Label>
          <KbTagEditor tags={tags} onChange={setTags} disabled={busy} />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3">
          <div>
            <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-text-muted">
              <span>Chunk size</span>
              <span className="font-mono text-brand-navy">{chunkSize}</span>
            </div>
            <Slider
              min={200}
              max={1500}
              step={32}
              value={[chunkSize]}
              onValueChange={(v) => {
                const next = v[0];
                setChunkSize(next);
                if (overlap >= next) setOverlap(Math.max(0, next - 1));
              }}
              disabled={busy}
            />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-text-muted">
              <span>Overlap</span>
              <span className="font-mono text-brand-navy">{overlap}</span>
            </div>
            <Slider
              min={0}
              max={Math.min(200, Math.max(0, chunkSize - 1))}
              step={8}
              value={[Math.min(overlap, chunkSize - 1)]}
              onValueChange={(v) => setOverlap(v[0])}
              disabled={busy}
            />
          </div>
        </div>
        <div className="mt-1 truncate font-mono text-[10px] text-text-muted">
          embed={doc.embeddingModel}
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          <Button size="sm" onClick={() => void save()} disabled={!dirty || busy}>
            <Save className="mr-1 h-3 w-3" />
            {savingMeta ? "Saving…" : "Save"}
          </Button>
          <Button size="sm" variant="outline" onClick={onReindex} disabled={busy}>
            <RefreshCw className={`mr-1 h-3 w-3 ${reindexing ? "animate-spin" : ""}`} />
            Re-index
          </Button>
          <Button size="sm" variant="outline" onClick={onToggle} disabled={busy}>
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
          <Button size="sm" variant="outline" onClick={onNewVersion} disabled={busy}>
            <FileUp className="mr-1 h-3 w-3" /> New version
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-red-200 text-red-700 hover:bg-red-50 hover:text-red-800"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
          >
            <Trash2 className="mr-1 h-3 w-3" />
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          <span className="font-medium text-text-secondary">Re-index</span> re-chunks the current
          file. <span className="font-medium text-text-secondary">New version</span> uploads
          replacement bytes. Prefer{" "}
          <span className="font-medium text-text-secondary">Sync from source_db</span> for the HDFC
          corpus.
        </p>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-text-muted">
          <span>id={doc.id}</span>
          <span>
            status={doc.status}
            {doc.enabled ? " · enabled" : " · disabled"}
          </span>
        </div>
        {dirty && (
          <p className="mt-2 text-[11px] text-amber-700">
            Unsaved changes
            {(chunkSize !== doc.chunkSize || overlap !== doc.overlap) &&
              " — changing chunk settings will re-index if the doc is enabled."}
          </p>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Chunks ({chunks.length})
          </div>
          <div className="text-[10px] text-text-muted">Updated by {doc.updatedBy}</div>
        </div>
        {chunks.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--border-token)] px-3 py-6 text-center text-[12px] text-text-muted">
            No chunks yet — enable and re-index, or sync from source_db.
          </div>
        ) : (
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
        )}
      </div>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{doc.title}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Permanently removes this document, its chunks, and source files. This cannot be undone.
              Corpus FAQs tied to the same product may also be removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault();
                void (async () => {
                  await Promise.resolve(onDelete());
                  setConfirmDelete(false);
                })();
              }}
            >
              {deleting ? "Deleting…" : "Delete permanently"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}
