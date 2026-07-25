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

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fromLabel: string;
  toLabel: string;
  from: { prompt: string; persona: PersonaState; voice: VoiceConfig; guardrails: Guardrails };
  to: { prompt: string; persona: PersonaState; voice: VoiceConfig; guardrails: Guardrails };
  onConfirm: (note: string) => void;
};

export function PublishDialog({ open, onOpenChange, fromLabel, toLabel, from, to, onConfirm }: Props) {
  const [confirmText, setConfirmText] = useState("");
  const [note, setNote] = useState("");
  const lines = diffStudioVersions(from, to);
  const added = lines.filter((l) => l.kind === "add").length;
  const removed = lines.filter((l) => l.kind === "del").length;

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
        <div className="space-y-3 text-[13px]">
          <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-3">
            <div className="text-text-secondary">
              Replacing live <span className="font-mono">{fromLabel}</span>. Full config diff:{" "}
              <span className="font-medium text-emerald-700">+{added}</span> ·{" "}
              <span className="font-medium text-red-700">−{removed}</span> lines (prompt + persona +
              voice + guardrails).
            </div>
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase text-text-muted">Change note</label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" />
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase text-text-muted">
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
            disabled={confirmText !== "PUBLISH"}
            onClick={() => onConfirm(note || `Published ${toLabel}`)}
          >
            Publish {toLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
