import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/*
 * Design.md `components.tag*` — decorative classification only (categories, labels), never
 * semantic status (that's Lozenge). Background is always transparent; only the accent border
 * carries color. `tag-gray` is the canonical example; other hues follow the same pattern.
 */
const tagVariants = cva(
  "inline-flex max-w-full items-center gap-050 whitespace-nowrap rounded-small border border-width-default bg-transparent text-body-small px-025 py-025 [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      hue: {
        gray: "border-border-accent-gray text-text-accent-gray",
        lime: "border-border-accent-lime text-text-accent-lime",
        red: "border-border-accent-red text-text-accent-red",
        orange: "border-border-accent-orange text-text-accent-orange",
        yellow: "border-border-accent-yellow text-text-accent-yellow",
        green: "border-border-accent-green text-text-accent-green",
        teal: "border-border-accent-teal text-text-accent-teal",
        blue: "border-border-accent-blue text-text-accent-blue",
        purple: "border-border-accent-purple text-text-accent-purple",
        magenta: "border-border-accent-magenta text-text-accent-magenta",
      },
    },
    defaultVariants: { hue: "gray" },
  },
);

export interface TagProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof tagVariants> {}

/** Decorative-only classification chip. Never use for status — see Lozenge. */
export const Tag = React.forwardRef<HTMLSpanElement, TagProps>(
  ({ className, hue, ...props }, ref) => (
    <span ref={ref} className={cn(tagVariants({ hue }), className)} {...props} />
  ),
);
Tag.displayName = "Tag";

export { tagVariants };
