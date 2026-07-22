import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { diffPrompts, type PromptVersion } from "@/data/prompt-studio-seed";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  base?: PromptVersion;
  current: { label: string; prompt: string };
};

export function DiffModal({ open, onOpenChange, base, current }: Props) {
  if (!base) return null;
  const lines = diffPrompts(base.prompt, current.prompt);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Diff · <span className="font-mono">{base.label}</span> → <span className="font-mono">{current.label}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken font-mono text-[12px]">
          {lines.map((l, i) => (
            <div
              key={i}
              className={`flex gap-2 border-b border-[var(--border-token)]/50 px-3 py-1 last:border-b-0 ${
                l.kind === "add"
                  ? "bg-emerald-50 text-emerald-900"
                  : l.kind === "del"
                    ? "bg-red-50 text-red-900"
                    : "text-text-secondary"
              }`}
            >
              <span className="select-none opacity-60">
                {l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "}
              </span>
              <span className="whitespace-pre-wrap break-words">{l.text || " "}</span>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
