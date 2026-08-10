import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/*
 * Design.md `components.lozenge*` — semantic status only. MUST keep a visible border (not a
 * fill-only pill); `lozenge-success` is the YAML's canonical example, other roles are inferred
 * from the same background-subtler / text-bolder / border-role triad.
 */
const lozengeVariants = cva(
  // min-h (not a fixed h) so labels with an icon/dot or slightly longer text never get clipped —
  // Design.md's 1.25rem is the resting/default size, not a hard ceiling on content.
  "inline-flex max-w-full items-center gap-050 whitespace-nowrap rounded-small border border-width-default text-body-small font-normal min-h-[1.25rem] px-050 py-025 leading-none [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "bg-background-neutral text-text border-border-bold",
        success: "bg-background-success-subtler text-text-success-bolder border-border-success",
        warning: "bg-background-warning-subtler text-text-warning-bolder border-border-warning",
        danger: "bg-background-danger-subtler text-text-danger-bolder border-border-danger",
        information:
          "bg-background-information-subtler text-text-information-bolder border-border-information",
        discovery:
          "bg-background-discovery-subtler text-text-discovery-bolder border-border-discovery",
        selected: "bg-background-selected text-text-selected border-border-selected",
      },
      size: {
        default: "",
        // lozenge-spacious
        spacious: "min-h-[2rem] rounded-medium text-body font-medium px-150 py-050 [&_svg]:size-4",
      },
    },
    defaultVariants: { tone: "neutral", size: "default" },
  },
);

export interface LozengeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof lozengeVariants> {}

/** The semantic roles a status chip may take. Use this for `Record<Status, LozengeTone>` maps. */
export type LozengeTone = NonNullable<LozengeProps["tone"]>;

/** Status indicator — bordered pill/rect. Never use for pure decoration (see Tag). */
export const Lozenge = React.forwardRef<HTMLSpanElement, LozengeProps>(
  ({ className, tone, size, ...props }, ref) => (
    <span ref={ref} className={cn(lozengeVariants({ tone, size }), className)} {...props} />
  ),
);
Lozenge.displayName = "Lozenge";

export { lozengeVariants };
