import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/*
 * Two sizes, named — the same `default`/`compact` vocabulary Button and
 * SelectTrigger use, and deliberately the same two heights as SelectTrigger so a
 * filter bar lines up.
 *
 * It was one fixed height before, so 24 call sites wrote `h-400` by hand and 26
 * wrote `text-body-small`, and the two sets were not the same sites. A 36px
 * Input beside a 32px select is what that looked like.
 */
const inputVariants = cva(
  "focus-ring flex w-full rounded-medium border border-border-input bg-background-input px-075 transition-colors duration-token-short file:border-0 file:bg-transparent file:font-medium file:text-text placeholder:text-text-subtlest hover:bg-background-input-hovered focus:bg-background-input-pressed focus:border-border-focused disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-border-danger",
  {
    variants: {
      size: {
        default: "h-9 py-075 text-body file:text-body",
        compact: "h-400 text-body-small file:text-body-small",
      },
    },
    defaultVariants: { size: "default" },
  },
);

export interface InputProps
  extends Omit<React.ComponentProps<"input">, "size">, VariantProps<typeof inputVariants> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, size, ...props }, ref) => {
    return (
      <input type={type} className={cn(inputVariants({ size }), className)} ref={ref} {...props} />
    );
  },
);
Input.displayName = "Input";

export { Input };
