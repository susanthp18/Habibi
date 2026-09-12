import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const ACTIVE = {
  brand: "border-border-brand bg-background-brand-subtlest text-text-brand",
  success: "border-border-success bg-background-success-subtler text-text-success-bolder",
  warning: "border-border-warning bg-background-warning-subtler text-text-warning-bolder",
  danger: "border-border-danger bg-background-danger-subtler text-text-danger-bolder",
  neutral:
    "border-border-accent-gray bg-background-accent-gray-subtlest text-text-accent-gray-bolder",
};

export type ChipTone = keyof typeof ACTIVE;

/** A pressable filter pill; `active` is its pressed state. */
export function Chip({
  active,
  onClick,
  tone = "brand",
  className,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  tone?: ChipTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-full border px-100 py-025 text-body-small transition-colors",
        active
          ? cn("font-medium", ACTIVE[tone])
          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
        className,
      )}
    >
      {children}
    </button>
  );
}
