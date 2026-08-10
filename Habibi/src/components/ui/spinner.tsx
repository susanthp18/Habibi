import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const spinnerVariants = cva("shrink-0", {
  variants: {
    size: {
      xsmall: "size-3",
      small: "size-4",
      medium: "size-6",
      large: "size-12",
      xlarge: "size-24",
    },
    tone: {
      subtle: "text-icon-subtle",
      inverse: "text-icon-inverse",
    },
  },
  defaultVariants: { size: "medium", tone: "subtle" },
});

export interface SpinnerProps
  extends React.SVGAttributes<SVGSVGElement>, VariantProps<typeof spinnerVariants> {}

/** Design.md `components.spinner*` — stroke-based loader, rotate + load-in motion. */
export const Spinner = React.forwardRef<SVGSVGElement, SpinnerProps>(
  ({ className, size, tone, ...props }, ref) => (
    <svg
      ref={ref}
      viewBox="0 0 24 24"
      fill="none"
      role="status"
      aria-label="Loading"
      className={cn(spinnerVariants({ size, tone }), "animate-spin", className)}
      style={{ animationDuration: "0.86s", animationTimingFunction: "cubic-bezier(0.4, 0.15, 0.6, 0.85)" }}
      {...props}
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeDasharray="60"
        strokeDashoffset="15"
        opacity="0.9"
      />
    </svg>
  ),
);
Spinner.displayName = "Spinner";

export { spinnerVariants };
