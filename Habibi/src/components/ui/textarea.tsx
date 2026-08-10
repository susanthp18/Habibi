import * as React from "react";

import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          "focus-ring flex min-h-[3.75rem] w-full rounded-medium border border-border-input bg-background-input px-075 py-075 text-body placeholder:text-text-subtlest hover:bg-background-input-hovered focus:bg-background-input-pressed focus:border-border-focused disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Textarea.displayName = "Textarea";

export { Textarea };
