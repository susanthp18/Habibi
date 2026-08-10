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
import { toast } from "sonner";
import { Lozenge } from "@/components/ui/lozenge";

/** Client-side text read cap — aligns with backend MAX_UPLOAD_BYTES (25 MiB) for PoC files. */
const MAX_KB_UPLOAD_BYTES = 25 * 1024 * 1024;
/** Bound preview tokenization to keep the wizard responsive on large files. */
const MAX_PREVIEW_TEXT_CHARS = 500_000;

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
    if (file.size > MAX_KB_UPLOAD_BYTES) {
      toast.error(`File too large (${Math.round(file.size / (1024 * 1024))} MB). Max ${MAX_KB_UPLOAD_BYTES / (1024 * 1024)} MB.`);
      setFile(null);
      setFileText("");
      setReading(false);
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setReading(true);
    const reader = new FileReader();
    let cancelled = false;
    reader.onload = () => {
      if (cancelled) return;
      setFileText(String(reader.result ?? "").slice(0, MAX_PREVIEW_TEXT_CHARS));
      setReading(false);
    };
    reader.onerror = () => {
      if (cancelled) return;
      setFileText("");
      setReading(false);
    };
    reader.readAsText(file);
    return () => {
      cancelled = true;
      reader.abort();
    };
  }, [file]);

  const preview = useMemo(
    () => previewChunksFromText(fileText.slice(0, MAX_PREVIEW_TEXT_CHARS), size, overlap),
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
          <DialogTitle className="flex items-center gap-100 text-base">
            <UploadCloud className="h-4 w-4 text-text-brand" />
            Upload document · Step {step} of 3
            {submitting ? " · Uploading…" : ""}
          </DialogTitle>
        </DialogHeader>

        {step === 1 && (
          <div className="space-y-150">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={submitting}
              className="grid w-full place-items-center rounded-large border-2 border-dashed border-border bg-surface-sunken/40 p-400 text-center transition-colors hover:border-border-brand/40 disabled:opacity-60"
            >
              <FileText className="h-400 w-400 text-text-subtlest" />
              <div className="mt-100 text-body font-medium text-text">
                {file ? file.name : "Choose a .md or .txt policy / benefits file"}
              </div>
              <div className="text-body-small text-text-subtlest">
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
            <div className="grid grid-cols-2 gap-150">
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
              <KbTagEditor tags={tags} onChange={setTags} disabled={submitting} className="mt-050" />
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-200">
            <div className="grid grid-cols-2 gap-200">
              <div>
                <div className="mb-050 flex items-center justify-between text-body-small text-text-subtlest">
                  <span>Chunk size (tokens)</span>
                  <span className="font-mono text-text">{size}</span>
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
                <div className="mb-050 flex items-center justify-between text-body-small text-text-subtlest">
                  <span>Overlap</span>
                  <span className="font-mono text-text">{overlap}</span>
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
            <div className="rounded-medium bg-background-brand-subtlest/60 p-100 text-body-small text-text-brand">
              {reading ? (
                "Reading file…"
              ) : (
                <>
                  Estimated ~<strong>{preview.count}</strong> chunks from this file · avg {size} words/window ·{" "}
                  {overlap} overlap
                  <span className="block text-body-small opacity-80">
                    Local word-window preview — server indexing uses tiktoken.
                  </span>
                </>
              )}
            </div>
            <div>
              <div className="mb-075 text-body-small font-semibold text-text-subtlest">
                First 5 chunks (from file)
              </div>
              {preview.samples.length === 0 ? (
                <div className="rounded-medium border border-dashed border-border p-200 text-body-small text-text-subtlest">
                  {reading ? "Loading preview…" : "No readable text in this file yet."}
                </div>
              ) : (
                <ul className="max-h-64 space-y-075 overflow-y-auto pr-050">
                  {preview.samples.map((s, i) => (
                    <li key={i} className="rounded-medium border border-border bg-surface p-100">
                      <div className="text-body-small font-mono text-text-subtlest">#{i + 1}</div>
                      <div className="mt-025 line-clamp-2 text-body-small text-text">{s}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-150">
            <div className="rounded-large border border-border bg-surface p-150">
              <div className="text-body-small text-text-subtlest">Ready to index</div>
              <div className="mt-050 font-medium text-text">
                {title || filename.replace(/\.[a-z]+$/i, "") || "Untitled"}
              </div>
              <div className="mt-100 grid grid-cols-2 gap-100 text-body-small text-text-subtle">
                <div>Type: <span className="text-text">{DOC_TYPE_LABEL[type]}</span></div>
                <div>Chunks: <span className="text-text">{preview.count}</span></div>
                <div>Chunk size: <span className="text-text">{size}</span></div>
                <div>Overlap: <span className="text-text">{overlap}</span></div>
              </div>
              {tags.length > 0 && (
                <div className="mt-100 flex flex-wrap gap-050">
                  {tags.map((t) => (
                    <Lozenge
                      key={t} tone="neutral">
                      #{t}
                    </Lozenge>
                  ))}
                </div>
              )}
            </div>
            <p className="text-body-small text-text-subtlest">
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
              Next <ChevronRight className="ml-050 h-3.5 w-3.5" />
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
