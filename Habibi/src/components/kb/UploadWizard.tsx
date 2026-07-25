import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DOC_TYPE_LABEL, type KbDocType } from "@/data/kb-seed";
import { previewChunksFromText, type KbUploadInput } from "@/api/kb";
import { KbTagEditor } from "@/components/kb/KbTagEditor";
import { UploadCloud, FileText, ChevronRight } from "lucide-react";

type Step = 1 | 2 | 3;

export function UploadWizard({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  /** Resolves when upload (+ optional link) is acknowledged by the API. Throw to keep dialog open. */
  onCreate: (input: KbUploadInput) => void | Promise<void>;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [fileText, setFileText] = useState("");
  const [reading, setReading] = useState(false);
  const [title, setTitle] = useState("");
  const [type, setType] = useState<KbDocType>("policy");
  const [tags, setTags] = useState<string[]>([]);
  const [size, setSize] = useState(512);
  const [overlap, setOverlap] = useState(64);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!file) {
      setFileText("");
      setReading(false);
      return;
    }
    setReading(true);
    const reader = new FileReader();
    reader.onload = () => {
      setFileText(String(reader.result ?? ""));
      setReading(false);
    };
    reader.onerror = () => {
      setFileText("");
      setReading(false);
    };
    reader.readAsText(file);
  }, [file]);

  const preview = useMemo(
    () => previewChunksFromText(fileText, size, overlap),
    [fileText, size, overlap],
  );
  const filename = file?.name ?? "";

  const reset = () => {
    setStep(1);
    setFile(null);
    setFileText("");
    setReading(false);
    setTitle("");
    setType("policy");
    setTags([]);
    setSize(512);
    setOverlap(64);
    setSubmitting(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  const close = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const create = async (indexNow: boolean) => {
    if (!file || submitting || reading) return;
    setSubmitting(true);
    try {
      await Promise.resolve(
        onCreate({
          file,
          title: title.trim() || undefined,
          type,
          chunkSize: size,
          overlap: Math.min(overlap, Math.max(0, size - 1)),
          indexNow,
          tags,
        }),
      );
      reset();
      onClose();
    } catch {
      // Parent toasts; keep dialog open for retry.
    } finally {
      setSubmitting(false);
    }
  };

  const canNext1 = Boolean(file) && !reading;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent
        className="max-w-2xl"
        onPointerDownOutside={(e) => submitting && e.preventDefault()}
        onEscapeKeyDown={(e) => submitting && e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <UploadCloud className="h-4 w-4 text-brand-primary" />
            Upload document · Step {step} of 3
            {submitting ? " · Uploading…" : ""}
          </DialogTitle>
        </DialogHeader>

        {step === 1 && (
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={submitting}
              className="grid w-full place-items-center rounded-lg border-2 border-dashed border-[var(--border-token)] bg-surface-sunken/40 p-8 text-center transition-colors hover:border-brand-primary/40 disabled:opacity-60"
            >
              <FileText className="h-8 w-8 text-text-muted" />
              <div className="mt-2 text-[13px] font-medium text-brand-navy">
                {file ? file.name : "Choose a .md or .txt policy / benefits file"}
              </div>
              <div className="text-[11px] text-text-muted">
                {file
                  ? `${Math.round(file.size / 1024)} KB · click to change`
                  : "PoC indexer supports markdown / plain text"}
              </div>
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.txt,.markdown,text/plain,text/markdown"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Filename</Label>
                <Input value={filename} readOnly placeholder="Select a file above" />
              </div>
              <div>
                <Label>Document type</Label>
                <Select
                  value={type}
                  onValueChange={(v) => setType(v as KbDocType)}
                  disabled={submitting}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(Object.keys(DOC_TYPE_LABEL) as KbDocType[]).map((k) => (
                      <SelectItem key={k} value={k}>{DOC_TYPE_LABEL[k]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label>Title (optional)</Label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Displayed in the library"
                disabled={submitting}
              />
            </div>
            <div>
              <Label>Tags</Label>
              <KbTagEditor tags={tags} onChange={setTags} disabled={submitting} className="mt-1" />
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-text-muted">
                  <span>Chunk size (tokens)</span>
                  <span className="font-mono text-brand-navy">{size}</span>
                </div>
                <Slider
                  min={200}
                  max={1500}
                  step={32}
                  value={[size]}
                  onValueChange={(v) => {
                    const next = v[0];
                    setSize(next);
                    if (overlap >= next) setOverlap(Math.max(0, next - 1));
                  }}
                  disabled={submitting}
                />
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-text-muted">
                  <span>Overlap</span>
                  <span className="font-mono text-brand-navy">{overlap}</span>
                </div>
                <Slider
                  min={0}
                  max={Math.min(200, Math.max(0, size - 1))}
                  step={8}
                  value={[Math.min(overlap, size - 1)]}
                  onValueChange={(v) => setOverlap(v[0])}
                  disabled={submitting}
                />
              </div>
            </div>
            <div className="rounded-md bg-brand-tint/60 p-2 text-[12px] text-brand-primary-dark">
              {reading ? (
                "Reading file…"
              ) : (
                <>
                  Estimated ~<strong>{preview.count}</strong> chunks from this file · avg {size} words/window ·{" "}
                  {overlap} overlap
                  <span className="block text-[11px] opacity-80">
                    Local word-window preview — server indexing uses tiktoken.
                  </span>
                </>
              )}
            </div>
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                First 5 chunks (from file)
              </div>
              {preview.samples.length === 0 ? (
                <div className="rounded-md border border-dashed border-[var(--border-token)] p-4 text-[12px] text-text-muted">
                  {reading ? "Loading preview…" : "No readable text in this file yet."}
                </div>
              ) : (
                <ul className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
                  {preview.samples.map((s, i) => (
                    <li key={i} className="rounded-md border border-[var(--border-token)] bg-surface-app p-2">
                      <div className="text-[10px] font-mono text-text-muted">#{i + 1}</div>
                      <div className="mt-0.5 line-clamp-2 text-[12px] text-text-primary">{s}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-3">
              <div className="text-[11px] uppercase tracking-wide text-text-muted">Ready to index</div>
              <div className="mt-1 font-medium text-brand-navy">
                {title || filename.replace(/\.[a-z]+$/i, "") || "Untitled"}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[12px] text-text-secondary">
                <div>Type: <span className="text-brand-navy">{DOC_TYPE_LABEL[type]}</span></div>
                <div>Chunks: <span className="text-brand-navy">{preview.count}</span></div>
                <div>Chunk size: <span className="text-brand-navy">{size}</span></div>
                <div>Overlap: <span className="text-brand-navy">{overlap}</span></div>
              </div>
              {tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {tags.map((t) => (
                    <span
                      key={t}
                      className="rounded-full bg-surface-sunken px-2 py-0.5 text-[10px] text-text-secondary"
                    >
                      #{t}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <p className="text-[12px] text-text-muted">
              {submitting
                ? "Uploading to MinIO and waiting for API acknowledgement…"
                : "File is stored in MinIO; indexing runs via the SKIP LOCKED worker."}
            </p>
          </div>
        )}

        <DialogFooter>
          {step > 1 && (
            <Button variant="ghost" onClick={() => setStep((step - 1) as Step)} disabled={submitting}>
              Back
            </Button>
          )}
          {step < 3 && (
            <Button
              onClick={() => setStep((step + 1) as Step)}
              disabled={(step === 1 && !canNext1) || submitting}
            >
              Next <ChevronRight className="ml-1 h-3.5 w-3.5" />
            </Button>
          )}
          {step === 3 && (
            <>
              <Button variant="outline" onClick={() => void create(false)} disabled={submitting || !file}>
                {submitting ? "Working…" : "Save as draft"}
              </Button>
              <Button onClick={() => void create(true)} disabled={submitting || !file}>
                {submitting ? "Uploading…" : "Index now"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
