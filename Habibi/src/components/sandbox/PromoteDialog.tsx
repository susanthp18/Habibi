import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { SlideToConfirm } from "@/components/ui/slide-to-confirm";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  promptLabel: string;
  kbLabel: string;
  scenarioLabel: string;
  onConfirm: () => void;
};

export function PromoteDialog({
  open,
  onOpenChange,
  promptLabel,
  kbLabel,
  scenarioLabel,
  onConfirm,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Promote to Production?</DialogTitle>
        </DialogHeader>
        <div className="space-y-150 text-body">
          <div className="rounded-medium border border-border bg-surface-sunken p-150 text-text-subtle">
            Prompt: <span className="font-mono">{promptLabel}</span>
            <br />
            KB: <span className="font-mono">{kbLabel}</span>
            <br />
            Last tested with: <span className="italic">{scenarioLabel}</span>
          </div>
          <div className="rounded-medium border border-border-warning bg-background-warning-subtler p-150 text-body-small text-text-warning-bolder">
            Promotes the persisted prompt, Agent Card, flow, guardrails, and selected KB snapshot.
            Rehearsal turns, simulated tool effects, scenario state, and temporary tuning controls
            reset and are not published.
          </div>
          <SlideToConfirm
            id="promote-confirm"
            label="Slide to promote"
            confirmedLabel="Promoting"
            onConfirm={onConfirm}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
