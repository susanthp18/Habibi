/**
 * Host slot "@/host/ToolReview": the approval decision on one tool revision.
 *
 * The engine has its own review route, but the Studio proxy denies it
 * (routers/agentstudio_gateway.py), so nothing reaches it through a generic
 * Studio session. A decision has to come from a named PayInt reviewer holding
 * perm-tool-approve, which is what POST /voice-studio/tools/… checks and
 * records in the change log — before the engine call and again after it.
 *
 * Approve and reject act on a submitted revision. Revoke is the emergency stop:
 * it takes a revision that released agents are calling right now out of service
 * mid-call, so it asks first.
 */
import { useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/config";
import { can, useMe } from "@/api/me";
import { reviewStudioToolRevision, type StudioToolRevision } from "@/api/studio-tools";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/use-confirm";

type Decision = "approved" | "rejected" | "revoked";

export default function ToolReview({
  toolUuid,
  revision,
  state,
  onReviewed,
}: {
  toolUuid: string;
  revision: number;
  state: StudioToolRevision["state"];
  onReviewed: () => void;
}) {
  const { data: me } = useMe();
  const { confirm, confirmDialog } = useConfirm();
  const [pending, setPending] = useState<Decision | null>(null);

  const mayReview = can(me, "perm-tool-approve");
  const isSubmitted = state === "submitted";
  const isCallable = state === "approved" || state === "legacy";
  if (!mayReview || (!isSubmitted && !isCallable)) return null;

  async function decide(decision: Decision) {
    if (
      decision === "revoked" &&
      !(await confirm({
        title: `Revoke revision ${revision}?`,
        description:
          "Released agents stop being able to call this tool immediately, including calls already in progress. Publishing an approved revision is the way back.",
        confirmLabel: "Revoke",
      }))
    )
      return;
    setPending(decision);
    try {
      await reviewStudioToolRevision(toolUuid, revision, decision);
      toast.success(`Revision ${revision} ${decision}`);
      onReviewed();
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setPending(null);
    }
  }

  return (
    <span className="inline-flex items-center gap-050">
      {isSubmitted && (
        <>
          <Button
            size="compact"
            disabled={pending !== null}
            onClick={() => void decide("approved")}
          >
            Approve
          </Button>
          <Button
            variant="subtle"
            size="compact"
            disabled={pending !== null}
            onClick={() => void decide("rejected")}
          >
            Reject
          </Button>
        </>
      )}
      {isCallable && (
        <Button
          variant="subtle"
          size="compact"
          disabled={pending !== null}
          onClick={() => void decide("revoked")}
        >
          Revoke
        </Button>
      )}
      {confirmDialog}
    </span>
  );
}
