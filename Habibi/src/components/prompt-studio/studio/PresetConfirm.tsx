import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useRef } from "react";
import type { PersonaPreset } from "@/api/types/prompt-studio";

/**
 * "Replace the system prompt?" -- asked before a preset discards authored text.
 *
 * The dialog animates out over ~150ms and reads its subject while `pending`
 * is already null, so the last non-null subject is held and the closing frame
 * says the same thing the open one did.
 */
export function PresetConfirm({
  pending,
  prompt,
  onCancel,
  onConfirm,
}: {
  pending: PersonaPreset | null;
  prompt: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const shownRef = useRef<PersonaPreset | null>(null);
  if (pending) shownRef.current = pending;
  const shown = shownRef.current;
  return (
    <AlertDialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <AlertDialogContent className="max-w-[28rem]">
        <AlertDialogHeader>
          <AlertDialogTitle>Replace the system prompt?</AlertDialogTitle>
          <AlertDialogDescription>
            Applying <span className="font-medium text-text">{shown?.label}</span> overwrites the
            prompt you have written and moves the persona sliders to that preset&rsquo;s values.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="rounded-medium border border-border bg-surface-sunken p-100">
          <div className="mb-050 text-body-small font-semibold text-text-subtlest">
            Your current prompt
          </div>
          <p className="line-clamp-3 whitespace-pre-wrap font-mono text-body-small text-text-subtle">
            {prompt.trim()}
          </p>
          <div className="mt-075 text-body-small text-text-subtlest">
            {prompt.length.toLocaleString()} characters. This is a draft edit — nothing published
            changes, and the toast that follows can undo it.
          </div>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep my prompt</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Replace with preset</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
