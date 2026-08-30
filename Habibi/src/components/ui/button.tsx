import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

/*
 * Design.md `components.button-*` recipe. Canonical appearances are
 * default/primary/subtle/warning/danger/discovery — the closed vocabulary the spec allows.
 * Legacy shadcn variant names (destructive/outline/secondary/ghost/link) are kept as aliases
 * onto the closest canonical appearance so the ~230 existing call sites keep compiling; Phase 3's
 * per-folder sweep replaces `variant="destructive"` etc. with the canonical name over time.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-075 whitespace-nowrap rounded-medium text-body font-medium cursor-pointer transition-colors duration-token-short ease-token-out-practical focus-ring disabled:pointer-events-none disabled:opacity-50 disabled:cursor-not-allowed [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-current",
  {
    variants: {
      variant: {
        // button-default: intentionally text-subtle, not full-contrast text — Design.md
        // explicitly says don't "fix" this so primary actions keep stronger visual emphasis.
        default:
          "bg-background-neutral-subtle text-text-subtle border border-border hover:bg-background-neutral-subtle-hovered active:bg-background-neutral-subtle-pressed",
        primary:
          "bg-background-brand-bold text-text-inverse hover:bg-background-brand-bold-hovered active:bg-background-brand-bold-pressed",
        subtle:
          "bg-background-neutral-subtle text-text-subtle border-transparent hover:bg-background-neutral-subtle-hovered active:bg-background-neutral-subtle-pressed",
        warning:
          "bg-background-warning-bold text-text-warning-inverse hover:bg-background-warning-bold-hovered active:bg-background-warning-bold-pressed",
        danger:
          "bg-background-danger-bold text-text-inverse hover:bg-background-danger-bold-hovered active:bg-background-danger-bold-pressed",
        discovery:
          "bg-background-discovery-bold text-text-inverse hover:bg-background-discovery-bold-hovered active:bg-background-discovery-bold-pressed",
        // --- legacy aliases (Phase 3 codemod target) ---
        destructive:
          "bg-background-danger-bold text-text-inverse hover:bg-background-danger-bold-hovered active:bg-background-danger-bold-pressed",
        outline:
          "bg-background-neutral-subtle text-text-subtle border border-border hover:bg-background-neutral-subtle-hovered",
        secondary:
          "bg-background-neutral-subtle text-text-subtle border-transparent hover:bg-background-neutral-subtle-hovered",
        ghost:
          "bg-transparent text-text-subtle border-transparent hover:bg-background-neutral-subtle-hovered",
        link: "text-link underline-offset-4 hover:underline border-transparent bg-transparent",
      },
      size: {
        default: "py-075 px-150",
        // Compact: dense surfaces only (tables, toolbars) — never a default.
        compact: "py-025 px-100 text-body-small",
        sm: "py-025 px-100 text-body-small",
        lg: "py-100 px-200",
        icon: "size-8 p-0",
        "icon-compact": "size-6 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Swaps the icon slot for a Spinner without shifting layout — never changes width/padding. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, ...props }, ref) => {
    if (asChild) {
      const Comp = Slot;
      return (
        <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props}>
          {children}
        </Comp>
      );
    }
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={props.disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading && (
          <Spinner
            size={size === "compact" || size === "sm" ? "xsmall" : "small"}
            tone={
              variant === "primary" || variant === "danger" || variant === "discovery"
                ? "inverse"
                : "subtle"
            }
          />
        )}
        <span className={cn(loading && "invisible", "contents")}>{children}</span>
      </button>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
