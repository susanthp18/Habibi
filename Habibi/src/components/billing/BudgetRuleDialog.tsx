import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { BudgetRule } from "@/data/billing-seed";

export function BudgetRuleDialog({
  open,
  onOpenChange,
  rule,
  onSave,
  onDelete,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  rule: BudgetRule | null;
  onSave: (r: BudgetRule) => void | Promise<void>;
  onDelete?: () => void | Promise<void>;
}) {
  const [draft, setDraft] = useState<BudgetRule>(
    rule ?? {
      id: `r_${Math.random().toString(36).slice(2, 8)}`,
      threshold: 80,
      channels: ["email:finance-ops"],
      action: "Notify finance-ops",
      severity: "warn",
    },
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setDraft(
        rule ?? {
          id: `r_${Math.random().toString(36).slice(2, 8)}`,
          threshold: 80,
          channels: ["email:finance-ops"],
          action: "Notify finance-ops",
          severity: "warn",
        },
      );
      setBusy(false);
    }
  }, [open, rule]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{rule ? "Edit rule" : "New budget rule"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label className="text-[12px]">Threshold (% of monthly cap)</Label>
            <Input
              type="number"
              min={1}
              max={200}
              value={draft.threshold}
              onChange={(e) => setDraft({ ...draft, threshold: +e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[12px]">Severity</Label>
            <Select
              value={draft.severity}
              onValueChange={(v) => setDraft({ ...draft, severity: v as BudgetRule["severity"] })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="info">Info</SelectItem>
                <SelectItem value="warn">Warn</SelectItem>
                <SelectItem value="critical">Critical</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-[12px]">Action</Label>
            <Input
              value={draft.action}
              onChange={(e) => setDraft({ ...draft, action: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[12px]">Channels (comma separated)</Label>
            <Input
              value={draft.channels.join(", ")}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  channels: e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              placeholder="email:finance-ops, slack:#billing"
            />
          </div>
        </div>
        <DialogFooter className="justify-between">
          <div>
            {onDelete && (
              <Button
                variant="ghost"
                className="text-rose-600 hover:text-rose-700"
                disabled={busy}
                onClick={() => {
                  void (async () => {
                    setBusy(true);
                    try {
                      await onDelete();
                    } catch {
                      // parent surfaces a toast and rethrows — swallow here to
                      // avoid an unhandled promise rejection.
                    } finally {
                      setBusy(false);
                    }
                  })();
                }}
              >
                Delete
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy || !draft.action.trim() || draft.channels.length === 0}
              onClick={() => {
                void (async () => {
                  setBusy(true);
                  try {
                    await onSave(draft);
                  } catch {
                    // parent surfaces a toast and rethrows — swallow here to
                    // avoid an unhandled promise rejection.
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
