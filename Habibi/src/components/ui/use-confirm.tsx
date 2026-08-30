import { useCallback, useEffect, useRef, useState } from "react";

import { createConfirmGate, type ConfirmGate } from "./confirm-gate";

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

export type ConfirmRequest = {
  title: string;
  /** What is actually at stake. Not a restatement of the button. */
  description?: string;
  /** Label for the destructive action. Say the verb, not "OK". */
  confirmLabel?: string;
  cancelLabel?: string;
};

/**
 * `window.confirm`'s ergonomics, without `window.confirm`.
 *
 * The house rule is that confirmations are asked in the product's own surface:
 * `window.confirm` paints as browser chrome titled "localhost:8080 says", blocks
 * the renderer, cannot be themed, and — as the Flow canvas found — freezes Radix
 * mid-close when called from inside a menu's `onSelect`, which needed a
 * `setTimeout(…, 0)` to work around.
 *
 * The rule kept being broken anyway, and it is worth being honest about why:
 * `if (!window.confirm(msg)) return;` is one line inside the handler that already
 * has the context, while an AlertDialog is a state variable, a piece of JSX at
 * the far end of the component, and a callback that has to carry the pending
 * item across. Six call sites took the one-liner. A ban with no ergonomic
 * replacement is a ban that loses.
 *
 * So this keeps the one-liner:
 *
 *     const { confirm, confirmDialog } = useConfirm();
 *     …
 *     if (!(await confirm({ title: "Delete rule?" }))) return;
 *     …
 *     return (<>{…}{confirmDialog}</>);
 *
 * The promise resolves false on cancel, Escape, or any other dismissal, so an
 * unanswered dialog can never read as consent.
 */
export function useConfirm() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  // Created once. The promise bookkeeping lives in `createConfirmGate`, which
  // has no React in it and is unit-tested — see confirm-gate.test.ts for the
  // property that matters: nothing except an explicit confirm resolves true.
  const gateRef = useRef<ConfirmGate | null>(null);
  if (gateRef.current === null) gateRef.current = createConfirmGate();
  const gate = gateRef.current;

  const settle = useCallback(
    (ok: boolean) => {
      setRequest(null);
      gate.settle(ok);
    },
    [gate],
  );

  const confirm = useCallback(
    (next: ConfirmRequest): Promise<boolean> => {
      const answer = gate.ask();
      setRequest(next);
      return answer;
    },
    [gate],
  );

  // An unmount is a dismissal, not a pause. Without this, navigating away with
  // a dialog open leaves the awaiting handler suspended for the life of the tab.
  useEffect(() => () => gate.settle(false), [gate]);

  const confirmDialog = (
    <AlertDialog
      open={request !== null}
      onOpenChange={(open) => {
        if (!open) settle(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{request?.title}</AlertDialogTitle>
          {request?.description ? (
            <AlertDialogDescription>{request.description}</AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => settle(false)}>
            {request?.cancelLabel ?? "Cancel"}
          </AlertDialogCancel>
          <AlertDialogAction onClick={() => settle(true)}>
            {request?.confirmLabel ?? "Confirm"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  return { confirm, confirmDialog };
}
