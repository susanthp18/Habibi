/**
 * Host slot "@/host/VersionRelease": under each version in the editor's version
 * history, who released it and why, and a rollback for earlier versions.
 *
 * Rollback copies the chosen version into the draft (engine, server-side, so
 * stored keys are kept), re-runs the release gate and publishes it as the next
 * version: history only grows, and the rollback is itself a release with a note.
 */
import { useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/config";
import { can, useMe } from "@/api/me";
import { type Release, useReleases, useRollbackAgent } from "@/api/voice-studio";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface VersionLike {
  id: number;
  version_number: number;
  status: string;
}

export default function VersionRelease({
  workflowId,
  version,
  onRolledBack,
}: {
  workflowId: number;
  version: VersionLike;
  onRolledBack: () => void;
}) {
  const releases = useReleases(workflowId);
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const release: Release | undefined = releases.data?.find(
    (r) => r.version === version.version_number,
  );
  // Archived = an earlier release. The live version and the draft are not rollback targets.
  const canRollBack = version.status === "archived" && can(me, "perm-agent-publish");

  if (!release && !canRollBack) return null;
  return (
    <div className="space-y-050 border-t border-border px-150 py-100 text-body-small">
      {release && (
        <p className="text-text">
          <span className="text-text-subtle">
            {release.action === "rollback" ? "Rollback" : "Release"} by {release.actor ?? "unknown"}
            :
          </span>{" "}
          {release.note}
        </p>
      )}
      {canRollBack && (
        <>
          <Button variant="subtle" size="compact" onClick={() => setOpen(true)}>
            Roll back to v{version.version_number}
          </Button>
          <RollbackDialog
            workflowId={workflowId}
            version={version}
            open={open}
            onOpenChange={setOpen}
            onRolledBack={onRolledBack}
          />
        </>
      )}
    </div>
  );
}

function RollbackDialog({
  workflowId,
  version,
  open,
  onOpenChange,
  onRolledBack,
}: {
  workflowId: number;
  version: VersionLike;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRolledBack: () => void;
}) {
  const rollback = useRollbackAgent(workflowId);
  const [note, setNote] = useState("");

  const submit = () =>
    rollback.mutate(
      { versionId: version.id, note: note.trim() },
      {
        onSuccess: (release) => {
          toast.success(`v${version.version_number} is live again as v${release.version ?? "?"}`);
          setNote("");
          onOpenChange(false);
          onRolledBack();
        },
        onError: (e) => toast.error(`Not rolled back: ${apiErrorMessage(e)}`),
      },
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[32rem]">
        <DialogHeader>
          <DialogTitle>Roll back to v{version.version_number}</DialogTitle>
          <DialogDescription>
            v{version.version_number} is re-checked and published as a new version, live on every
            channel this agent answers. Unpublished edits in the current draft are replaced.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-100 px-300">
          <Label htmlFor={`vs-rollback-${version.id}`}>Why</Label>
          <Textarea
            id={`vs-rollback-${version.id}`}
            rows={3}
            value={note}
            maxLength={2000}
            placeholder="e.g. v5 booked duplicate callbacks"
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="subtle" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={note.trim().length < 3}
            loading={rollback.isPending}
            onClick={submit}
          >
            Roll back
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
