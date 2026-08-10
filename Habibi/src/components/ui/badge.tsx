import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/*
 * Design.md `components.badge*` — compact count primitive only (unread counts, list totals).
 * For status use Lozenge; for decorative labels use Tag.
 */
const badgeVariants = cva(
  "inline-flex items-center justify-center min-w-[1.5rem] rounded-xsmall px-050 py-0 text-body-small font-medium",
  {
    variants: {
      variant: {
        default: "bg-background-accent-gray-subtler text-text",
        success: "bg-background-success-subtler text-text-success-bolder",
        // --- legacy shadcn aliases (Phase 3 codemod target) ---
        secondary: "bg-background-accent-gray-subtler text-text",
        destructive: "bg-background-danger-subtler text-text-danger-bolder",
        outline: "bg-transparent text-text border border-border",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
