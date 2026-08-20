import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  diffStudioVersions,
  type Guardrails,
  type PersonaState,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import type { CompileReport } from "@/api/agent-studio";
import { CompileReportList } from "@/components/prompt-studio/AgentCardPanels";
import type { FlowIssue } from "@/api/flow";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fromLabel: string;
  toLabel: string;
  from: { prompt: string; persona: PersonaState; voice: VoiceConfig; guardrails: Guardrails };
  to: { prompt: string; persona: PersonaState; voice: VoiceConfig; guardrails: Guardrails };
  onConfirm: (note: string) => void;
  flowIssues?: FlowIssue[];
  compileReport?: CompileReport | null;
  compileBusy?: boolean;
};

export function PublishDialog({
  open,
  onOpenChange,
  fromLabel,
  toLabel,
  from,
  to,
  onConfirm,
  flowIssues = [],
  compileReport = null,
  compileBusy = false,
}: Props) {
  const [confirmText, setConfirmText] = useState("");
  const [note, setNote] = useState("");
  const lines = diffStudioVersions(from, to);
  const added = lines.filter((l) => l.kind === "add").length;
  const removed = lines.filter((l) => l.kind === "del").length;
  const errors = flowIssues.filter((i) => i.severity === "error");
  const compileFailed = (compileReport?.gates ?? []).some((g) => g.status === "fail");
  // Publish waits for the compiler.
  //
  // `compileReport` is the *previous* run until the new one lands, so opening
  // this dialog a second time showed the last card's gate list under a
  // "Running compiler…" banner, and `blocked` was decided by it: a run that
  // failed last time disabled Confirm for a config that now passes, and one
  // that passed left Confirm live while the real answer was still in flight.
  const blocked = errors.length > 0 || compileFailed || compileBusy;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) {
          setConfirmText("");
          setNote("");
        }
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Publish <span className="font-mono">{toLabel}</span>?
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-150 text-body">
          {compileBusy && (
            <div className="rounded-medium border border-border bg-surface-sunken p-150 text-body-small text-text-subtle">
              Running compiler G0–G14…
            </div>
          )}
          {compileReport && !compileBusy && (
            <div className="rounded-medium border border-border p-150">
              <div className="mb-075 text-body-small font-semibold">Compiler report</div>
              <CompileReportList report={compileReport} />
            </div>
          )}
          {errors.length > 0 && (
            <div className="rounded-medium border border-border-danger bg-background-danger-subtler p-150 text-body-small text-text-danger-bolder">
              <div className="font-semibold">Flow compiler failed — cannot publish</div>
              <ul className="mt-050 list-disc space-y-025 pl-200">
                {errors.map((issue, i) => (
                  <li key={`${issue.code}-${i}`}>{issue.message}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="rounded-medium border border-border bg-surface-sunken p-150">
            <div className="text-text-subtle">
              {fromLabel === "nothing live" ? (
                "First publish — nothing is live yet. Full config: "
              ) : (
                <>
                  Replacing live <span className="font-mono">{fromLabel}</span>. Full config diff:{" "}
                </>
              )}
              <span className="font-medium text-text-success-bolder">+{added}</span> ·{" "}
              <span className="font-medium text-text-danger-bolder">−{removed}</span> lines (prompt + persona +
              voice + guardrails).
            </div>
          </div>
          <div>
            <label className="text-body-small font-semibold text-text-subtlest">Change note</label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" />
          </div>
          <div>
            <label className="text-body-small font-semibold text-text-subtlest">
              Type <span className="font-mono">PUBLISH</span> to confirm
            </label>
            <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="PUBLISH" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={blocked || confirmText !== "PUBLISH"}
            onClick={() => onConfirm(note || `Published ${toLabel}`)}
          >
            Publish {toLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
