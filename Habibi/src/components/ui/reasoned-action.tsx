import { useId, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { ActionAvailability } from "@/lib/agent-roster";
import { cn } from "@/lib/utils";

/**
 * A button that stays in the tab order when it cannot act and says why.
 * `disabled` removes a control from the keyboard and from every assistive
 * reader with it; aria-disabled keeps it reachable, the reason rides
 * aria-describedby, and the click is refused rather than removed.
 */
export function ReasonedAction({
  availability,
  busy = false,
  onClick,
  children,
}: {
  availability: ActionAvailability;
  busy?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  const describedBy = useId();
  const blocked = !availability.allowed;
  return (
    <>
      <Button
        type="button"
        variant="outline"
        loading={busy}
        disabled={busy}
        aria-disabled={blocked || undefined}
        aria-describedby={blocked ? describedBy : undefined}
        title={availability.reason}
        className={cn(
          blocked &&
            "aria-disabled:cursor-not-allowed aria-disabled:opacity-50 aria-disabled:hover:bg-background-neutral-subtle",
        )}
        onClick={() => {
          if (blocked || busy) return;
          onClick();
        }}
      >
        {children}
      </Button>
      {blocked ? (
        <span id={describedBy} className="sr-only">
          {availability.reason}
        </span>
      ) : null}
    </>
  );
}
