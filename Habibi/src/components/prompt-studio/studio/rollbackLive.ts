/**
 * Roll production back to the prior deployment and adopt that version into
 * the editor. Refuses over unsaved edits -- adopting would discard them -- and
 * asks first: production switches on the click.
 */
import { toast } from "sonner";
import type { ConfirmRequest } from "@/components/ui/use-confirm";
import type { PromptVersion } from "@/api/types/prompt-studio";
import type { BotDeployment } from "@/api/prompt-studio";
import { adopted, type EditorFields } from "./studioDraft";

export async function rollbackLive({
  targetId,
  unsaved,
  confirm,
  rollback,
  refetchVersions,
  adoptVersion,
}: {
  targetId: string | null | undefined;
  unsaved: boolean;
  confirm: (req: ConfirmRequest) => Promise<boolean>;
  rollback: (targetId: string) => Promise<BotDeployment>;
  refetchVersions: () => Promise<PromptVersion[] | undefined>;
  adoptVersion: (fields: EditorFields, opts: { draftId: string | null }) => void;
}): Promise<void> {
  if (!targetId) {
    toast.info("No prior production deployment to roll back to.");
    return;
  }
  if (unsaved) {
    toast.error("Save or discard the unsaved edits before rolling back.");
    return;
  }
  if (
    !(await confirm({
      title: "Roll back the live config?",
      description: `Production switches to ${targetId} now; the editor adopts that version.`,
      confirmLabel: "Roll back",
    }))
  )
    return;
  try {
    const dep = await rollback(targetId);
    const live = (await refetchVersions())?.find((v) => v.id === dep.promptVersionId);
    if (live) adoptVersion({ ...adopted(live), flow: live.flow ?? null }, { draftId: null });
    toast.success(`Rolled back live config to ${dep.promptVersionId}`);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "Rollback failed");
  }
}
