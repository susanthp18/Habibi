import { useMemo, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { chunkPreview, DOC_TYPE_LABEL, type KbDocType, type KbDocument } from "@/data/kb-seed";
import { UploadCloud, FileText, ChevronRight } from "lucide-react";

type Step = 1 | 2 | 3;

export function UploadWizard({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (doc: KbDocument, indexNow: boolean) => void;
}) {
  const [step, setStep] = useState<Step>(1);
  const [filename, setFilename] = useState("");
  const [title, setTitle] = useState("");
  const [type, setType] = useState<KbDocType>("policy");
  const [size, setSize] = useState(512);
  const [overlap, setOverlap] = useState(64);

  const preview = useMemo(() => chunkPreview(size, overlap), [size, overlap]);

  const reset = () => {
    setStep(1);
    setFilename("");
    setTitle("");
    setType("policy");
    setSize(512);
    setOverlap(64);
  };

  const close = () => {
    reset();
    onClose();
  };

  const create = (indexNow: boolean) => {
    const id = `d-${Date.now()}`;
    onCreate(
      {
        id,
        title: title.trim() || filename.replace(/\.[a-z]+$/i, ""),
        filename: filename.trim() || "untitled.pdf",
        type,
        version: "v1.0",
        status: indexNow ? "indexing" : "draft",
        enabled: indexNow,
        chunks: preview.count,
        chunkSize: size,
        overlap,
        embeddingModel: "text-embedding-3-small",
        updatedBy: "You",
        lastIndexed: new Date().toISOString(),
        tags: [],
      },
      indexNow,
    );
    close();
  };

  const canNext1 = filename.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <UploadCloud className="h-4 w-4 text-brand-primary" />
            Upload document · Step {step} of 3
          </DialogTitle>
        </DialogHeader>

        {step === 1 && (
          <div className="space-y-3">
            <div className="grid place-items-center rounded-lg border-2 border-dashed border-[var(--border-token)] bg-surface-sunken/40 p-8 text-center">
              <FileText className="h-8 w-8 text-text-muted" />
              <div className="mt-2 text-[13px] font-medium text-brand-navy">
                Drop a PDF or DOCX here
              </div>
              <div className="text-[11px] text-text-muted">or enter a filename to simulate</div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Filename</Label>
                <Input
                  value={filename}
                  onChange={(e) => setFilename(e.target.value)}
                  placeholder="e.g. new_policy.pdf"
                />
              </div>
              <div>
                <Label>Document type</Label>
                <Select value={type} onValueChange={(v) => setType(v as KbDocType)}>
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
              />
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
                <Slider min={200} max={1500} step={32} value={[size]} onValueChange={(v) => setSize(v[0])} />
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-text-muted">
                  <span>Overlap</span>
                  <span className="font-mono text-brand-navy">{overlap}</span>
                </div>
                <Slider min={0} max={200} step={8} value={[overlap]} onValueChange={(v) => setOverlap(v[0])} />
              </div>
            </div>
            <div className="rounded-md bg-brand-tint/60 p-2 text-[12px] text-brand-primary-dark">
              Will produce ~<strong>{preview.count}</strong> chunks · avg {size} tok · {overlap} overlap
            </div>
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                First 5 chunks
              </div>
              <ul className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
                {preview.samples.map((s, i) => (
                  <li key={i} className="rounded-md border border-[var(--border-token)] bg-surface-app p-2">
                    <div className="text-[10px] font-mono text-text-muted">#{i + 1}</div>
                    <div className="mt-0.5 line-clamp-2 text-[12px] text-text-primary">{s}</div>
                  </li>
                ))}
              </ul>
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
            </div>
            <p className="text-[12px] text-text-muted">
              Indexing runs in the background — the doc will appear in the library immediately.
            </p>
          </div>
        )}

        <DialogFooter>
          {step > 1 && (
            <Button variant="ghost" onClick={() => setStep((step - 1) as Step)}>
              Back
            </Button>
          )}
          {step < 3 && (
            <Button onClick={() => setStep((step + 1) as Step)} disabled={step === 1 && !canNext1}>
              Next <ChevronRight className="ml-1 h-3.5 w-3.5" />
            </Button>
          )}
          {step === 3 && (
            <>
              <Button variant="outline" onClick={() => create(false)}>Save as draft</Button>
              <Button onClick={() => create(true)}>Index now</Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
