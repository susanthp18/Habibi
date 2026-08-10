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
        <p className="text-body-small text-text-subtlest">
          Includes system prompt, persona traits, voice settings, and guardrails.
        </p>
        <div className="rounded-medium border border-border bg-surface-sunken font-mono text-body-small">
          {lines.map((l, i) => (
            <div
              key={i}
              className={`flex gap-100 border-b border-border/50 px-150 py-050 last:border-b-0 ${
                l.kind === "add"
                  ? "bg-background-success-subtler text-text-success-bolder"
                  : l.kind === "del"
                    ? "bg-background-danger-subtler text-text-danger-bolder"
                    : "text-text-subtle"
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
