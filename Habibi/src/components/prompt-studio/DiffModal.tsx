import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  diffStudioVersions,
  type Guardrails,
  type PersonaState,
  type PromptVersion,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";

type Snapshot = {
  label: string;
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  base?: PromptVersion;
  current: Snapshot;
};

export function DiffModal({ open, onOpenChange, base, current }: Props) {
  if (!base) return null;
  const lines = diffStudioVersions(base, current);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Diff · <span className="font-mono">{base.label}</span> →{" "}
            <span className="font-mono">{current.label}</span>
          </DialogTitle>
        </DialogHeader>
        <p className="text-[11px] text-text-muted">
          Includes system prompt, persona traits, voice settings, and guardrails.
        </p>
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
