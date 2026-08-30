import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  diffStudioVersions,
  type Guardrails,
  type PersonaState,
  type PromptVersion,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import { stableStringify } from "@/lib/stable-stringify";

type Snapshot = {
  label: string;
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  /**
   * A version stores six things and this modal compared four of them.
   *
   * `flow` and `agentCard` are stored on `prompt_versions` and shipped by
   * publish, so rewiring the conversation graph, adding a tool, binding a
   * connector or moving the canary produced a diff reading "no changes" —
   * on the screen an operator opens specifically to find out what changed
   * between two versions. The publish dialog had already been fixed to report
   * both; this is the same fix on the compare view.
   *
   * Reported as changed/unchanged rather than folded into the line diff, for
   * the same reason it is there: rendering structured JSON as added and removed
   * text lines yields a number derived from the change that says nothing about
   * it.
   */
  flow?: unknown;
  agentCard?: unknown;
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
  const flowChanged = stableStringify(base.flow ?? null) !== stableStringify(current.flow ?? null);
  const cardChanged =
    stableStringify(base.agentCard ?? null) !== stableStringify(current.agentCard ?? null);
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
          Text diff covers the system prompt, persona traits, voice settings and guardrails. The
          conversation graph is{" "}
          <span className={flowChanged ? "font-medium text-text-warning-bolder" : undefined}>
            {flowChanged ? "changed" : "unchanged"}
          </span>{" "}
          and the agent card is{" "}
          <span className={cardChanged ? "font-medium text-text-warning-bolder" : undefined}>
            {cardChanged ? "changed" : "unchanged"}
          </span>
          .
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
