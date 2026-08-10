import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "focus-ring flex h-9 w-full rounded-medium border border-border-input bg-background-input px-075 py-075 text-body transition-colors duration-token-short file:border-0 file:bg-transparent file:text-body file:font-medium file:text-text placeholder:text-text-subtlest hover:bg-background-input-hovered focus:bg-background-input-pressed focus:border-border-focused disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-border-danger",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
