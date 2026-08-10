import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/*
 * Design.md `components.link-*` — default/subtle/inverse appearances. Use for any styled
 * anchor or router-link text; migrate ad hoc anchor className strings onto this opportunistically.
 */
const linkVariants = cva("rounded-xsmall focus-ring", {
  variants: {
    appearance: {
      default: "text-link underline hover:no-underline",
      subtle: "text-text-subtle no-underline hover:underline",
      inverse: "text-text-inverse underline hover:no-underline",
    },
  },
  defaultVariants: { appearance: "default" },
});

export interface LinkTextProps
  extends React.AnchorHTMLAttributes<HTMLAnchorElement>, VariantProps<typeof linkVariants> {}

/** Plain-anchor link styling per Design.md. For in-app navigation prefer the router's Link. */
export const LinkText = React.forwardRef<HTMLAnchorElement, LinkTextProps>(
  ({ className, appearance, ...props }, ref) => (
    <a ref={ref} className={cn(linkVariants({ appearance }), className)} {...props} />
  ),
);
LinkText.displayName = "LinkText";

export { linkVariants };
