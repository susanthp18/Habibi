import { useEffect, useRef, useState } from "react";
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
import { toast } from "sonner";

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

  const tagsKey = doc.tags.join("\0");

  // Mirrors `dirty` so the sync effect can read it without depending on it
  // (which would re-run the effect on every keystroke).
  const dirtyRef = useRef(false);
  const [staleRemote, setStaleRemote] = useState(false);

  useEffect(() => {
    // Never clobber in-progress edits. A remote change landing mid-edit used to
    // silently replace what the user had typed with the server's values.
    if (dirtyRef.current) {
      setStaleRemote(true);
      return;
    }
    setStaleRemote(false);
    setTitle(doc.title);
    setTags(doc.tags);
    setChunkSize(doc.chunkSize);
    setOverlap(doc.overlap);
  }, [doc.id, doc.title, tagsKey, doc.chunkSize, doc.overlap]);

  // Selecting a different document always wins over a pending edit.
  useEffect(() => {
    dirtyRef.current = false;
    setStaleRemote(false);
    setTitle(doc.title);
    setTags(doc.tags);
    setChunkSize(doc.chunkSize);
    setOverlap(doc.overlap);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- identity change only
  }, [doc.id]);

  const dirty =
    title.trim() !== doc.title ||
    chunkSize !== doc.chunkSize ||
    overlap !== doc.overlap ||
    tags.join("\0") !== doc.tags.join("\0");
  dirtyRef.current = dirty;

  const busy = savingMeta || reindexing || deleting;

  const save = async () => {
    if (!dirty || busy) return;
    const nextTitle = title.trim() || doc.title;
    const safeOverlap = Math.min(overlap, Math.max(0, chunkSize - 1));
    try {
      await Promise.resolve(
        onSaveMeta({
          title: nextTitle,
          tags,
          chunkSize,
          overlap: safeOverlap,
        }),
      );
      dirtyRef.current = false;
      setStaleRemote(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save document");
    }
  };

  return (
    <aside className="flex h-full max-h-[inherit] min-h-0 w-full flex-col overflow-hidden rounded-large border border-border bg-surface">
      <div className="shrink-0 border-b border-border p-150">
        <div className="flex items-start justify-between gap-100">
          <div className="min-w-0 flex-1 space-y-100">
            <div className="text-body-small font-semibold text-text-subtlest">
              {DOC_TYPE_LABEL[doc.type]} · {doc.version}
            </div>
            <div>
              <Label className="text-body-small text-text-subtlest">Title</Label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="mt-050 h-400 text-body font-semibold"
                disabled={busy}
              />
            </div>
            <div className="truncate text-body-small text-text-subtlest">{doc.filename}</div>
            {staleRemote && (
              <div className="rounded-medium border border-border-warning bg-background-warning-subtler px-100 py-050 text-body-small text-text-warning-bolder">
                This document changed elsewhere. Your edits are kept — saving
                will overwrite the newer version.
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-medium p-050 text-text-subtlest hover:bg-surface-sunken"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-150 space-y-075">
          <Label className="text-body-small text-text-subtlest">Tags</Label>
          <KbTagEditor tags={tags} onChange={setTags} disabled={busy} />
        </div>

        <div className="mt-150 grid grid-cols-2 gap-150">
          <div>
            <div className="mb-050 flex items-center justify-between text-body-small text-text-subtlest">
              <span>Chunk size</span>
              <span className="font-mono text-text">{chunkSize}</span>
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
            <div className="mb-050 flex items-center justify-between text-body-small text-text-subtlest">
              <span>Overlap</span>
              <span className="font-mono text-text">{overlap}</span>
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
        <div className="mt-050 truncate font-mono text-body-small text-text-subtlest">
          embed={doc.embeddingModel}
        </div>

        <div className="mt-150 flex flex-wrap gap-075">
          <Button size="sm" onClick={() => void save()} disabled={!dirty || busy}>
            <Save className="mr-050 h-3 w-3" />
            {savingMeta ? "Saving…" : "Save"}
          </Button>
          <Button size="sm" variant="outline" onClick={onReindex} disabled={busy}>
            <RefreshCw className={`mr-050 h-3 w-3 ${reindexing ? "animate-spin" : ""}`} />
            Re-index
          </Button>
          <Button size="sm" variant="outline" onClick={onToggle} disabled={busy}>
            {doc.enabled ? (
              <>
                <PowerOff className="mr-050 h-3 w-3" /> Disable
              </>
            ) : (
              <>
                <Power className="mr-050 h-3 w-3" /> Enable
              </>
            )}
          </Button>
          <Button size="sm" variant="outline" onClick={onNewVersion} disabled={busy}>
            <FileUp className="mr-050 h-3 w-3" /> New version
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-border-danger-subtle text-text-danger-bolder hover:bg-background-danger-subtler hover:text-text-danger-bolder"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
          >
            <Trash2 className="mr-050 h-3 w-3" />
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </div>
        <p className="mt-100 text-body-small leading-relaxed text-text-subtlest">
          <span className="font-medium text-text-subtle">Re-index</span> re-chunks the current
          file. <span className="font-medium text-text-subtle">New version</span> uploads
          replacement bytes. Prefer{" "}
          <span className="font-medium text-text-subtle">Sync from source_db</span> for the HDFC
          corpus.
        </p>
        <div className="mt-100 flex flex-wrap gap-x-150 gap-y-050 font-mono text-body-small text-text-subtlest">
          <span>id={doc.id}</span>
          <span>
            status={doc.status}
            {doc.enabled ? " · enabled" : " · disabled"}
          </span>
        </div>
        {dirty && (
          <p className="mt-100 text-body-small text-text-warning-bolder">
            Unsaved changes
            {(chunkSize !== doc.chunkSize || overlap !== doc.overlap) &&
              " — changing chunk settings will re-index if the doc is enabled."}
          </p>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-150">
        <div className="mb-100 flex items-center justify-between">
          <div className="text-body-small font-semibold text-text-subtlest">
            Chunks ({chunks.length})
          </div>
          <div className="text-body-small text-text-subtlest">Updated by {doc.updatedBy}</div>
        </div>
        {chunks.length === 0 ? (
          <div className="rounded-medium border border-dashed border-border px-150 py-300 text-center text-body-small text-text-subtlest">
            No chunks yet — enable and re-index, or sync from source_db.
          </div>
        ) : (
          <ul className="space-y-075">
            {chunks.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => onOpenChunk(c)}
                  className="w-full rounded-medium border border-border bg-surface p-100 text-left transition-colors hover:border-border-brand/40 hover:bg-background-brand-subtlest/40"
                >
                  <div className="flex items-center justify-between text-body-small text-text-subtlest">
                    <span className="font-mono">#{c.index}</span>
                    <span>
                      {c.tokens} tok · {c.hits} hits
                    </span>
                  </div>
                  <div className="mt-025 truncate text-body-small font-medium text-text-subtle">
                    {c.heading}
                  </div>
                  <div className="mt-025 line-clamp-2 text-body-small text-text">{c.text}</div>
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
              className="bg-background-danger-bold hover:bg-background-danger-bold-pressed"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault();
                void (async () => {
                  try {
                    await Promise.resolve(onDelete());
                    setConfirmDelete(false);
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : "Failed to delete document");
                  }
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
