import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/*
 * Design.md `components.section-message*` — inline page-level status/system notice.
 * `section-message-information` is the YAML's only literal example; the other 4 roles are
 * inferred from the same background-role + icon-role + neutral-body-text shape.
 *
 * Critical rule (previously violated by the old alert.tsx this replaces): body copy — and the
 * title — stay neutral `text` always. ONLY the icon and the background carry semantic color.
 * Tinting body text on a colored panel is the most common drift pattern Design.md calls out.
 */
const sectionMessageVariants = cva("relative w-full rounded-large p-200 flex gap-200", {
  variants: {
    variant: {
      information: "bg-background-information",
      warning: "bg-background-warning",
      error: "bg-background-danger",
      success: "bg-background-success",
      discovery: "bg-background-discovery",
    },
  },
  defaultVariants: { variant: "information" },
});

const iconColorByVariant: Record<NonNullable<SectionMessageProps["variant"]>, string> = {
  information: "text-icon-information",
  warning: "text-icon-warning",
  error: "text-icon-danger",
  success: "text-icon-success",
  discovery: "text-icon-discovery",
};

export interface SectionMessageProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof sectionMessageVariants> {
  /** Icon is mandatory — a SectionMessage without one loses its semantic affordance. */
  icon: LucideIcon;
  title: React.ReactNode;
  children?: React.ReactNode;
}

export const SectionMessage = React.forwardRef<HTMLDivElement, SectionMessageProps>(
  ({ className, variant = "information", icon: Icon, title, children, ...props }, ref) => (
    <div ref={ref} role="alert" className={cn(sectionMessageVariants({ variant }), className)} {...props}>
      <Icon
        aria-hidden="true"
        className={cn("size-4 shrink-0 mt-025", iconColorByVariant[variant ?? "information"])}
      />
      <div className="flex flex-col gap-050 min-w-0">
        <div className="heading-xsmall text-text">{title}</div>
        {children ? <div className="text-body text-text">{children}</div> : null}
      </div>
    </div>
  ),
);
SectionMessage.displayName = "SectionMessage";

export { sectionMessageVariants };
