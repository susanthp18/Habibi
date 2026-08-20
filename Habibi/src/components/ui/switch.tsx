import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";
import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";

/*
 * Design.md `components.toggle*` — 32x16 (space-400 x space-200) track, radius-full, success
 * track only when checked, thumb travels space-200 via a transform transition (short duration +
 * out-practical easing, not a jump). A tick/cross glyph sits in the uncovered track segment so
 * state reads without relying on color alone.
 */
/**
 * A switch renders as a bare `<button role="switch">` with no text of its own,
 * so its accessible name has to be supplied. Every one of the ten call sites in
 * this app put the label in a sibling `<div>` instead — which looks right and
 * announces as "switch, not pressed", with no indication of *what* is being
 * toggled. Guardrails alone has five of them.
 *
 * Requiring one of the two labelling attributes in the type makes that
 * impossible to forget: the omission is a compile error at the call site rather
 * than something an audit has to keep re-finding.
 */
type SwitchProps = React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> &
  (
    | { "aria-label": string; "aria-labelledby"?: never }
    | { "aria-labelledby": string; "aria-label"?: never }
  );

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  SwitchProps
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      "group focus-ring peer relative inline-flex h-200 w-400 shrink-0 cursor-pointer items-center rounded-full p-025 transition-colors duration-token-short disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-background-success-bold data-[state=unchecked]:bg-background-neutral-bold",
      className,
    )}
    {...props}
    ref={ref}
  >
    <Check
      aria-hidden="true"
      className="absolute left-025 size-[0.5625rem] text-icon-inverse opacity-0 group-data-[state=checked]:opacity-100"
    />
    <X
      aria-hidden="true"
      className="absolute right-025 size-[0.5625rem] text-icon-inverse opacity-100 group-data-[state=checked]:opacity-0"
    />
    <SwitchPrimitives.Thumb
      className={cn(
        "pointer-events-none relative block size-3 rounded-full bg-icon-inverse shadow-raised transition-transform duration-token-short ease-token-out-practical data-[state=checked]:translate-x-200 data-[state=unchecked]:translate-x-0",
      )}
    />
  </SwitchPrimitives.Root>
));
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
export type { SwitchProps };
