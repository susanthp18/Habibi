import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  promptLabel: string;
  kbLabel: string;
  scenarioLabel: string;
  tuningSummary?: string;
  onConfirm: () => void;
};

export function PromoteDialog({
  open,
  onOpenChange,
  promptLabel,
  kbLabel,
  scenarioLabel,
  tuningSummary,
  onConfirm,
}: Props) {
  const [text, setText] = useState("");
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setText("");
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Promote to Production?</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-[13px]">
          <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-3 text-text-secondary">
            Prompt: <span className="font-mono">{promptLabel}</span>
            <br />
            KB: <span className="font-mono">{kbLabel}</span>
            <br />
            {tuningSummary && (
              <>
                Tuning: <span className="font-mono">{tuningSummary}</span>
                <br />
              </>
            )}
            Last tested with: <span className="italic">{scenarioLabel}</span>
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase text-text-muted">
              Type <span className="font-mono">PROMOTE</span> to confirm
            </label>
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="PROMOTE" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={text !== "PROMOTE"} onClick={onConfirm}>
            Promote
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
