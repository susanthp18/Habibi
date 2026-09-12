import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const ACTIVE = {
  brand: "border-border-brand bg-background-brand-subtlest font-semibold text-text-brand",
  success: "border-border-success bg-background-success-bold text-white",
  warning: "border-border-warning bg-background-warning-bold text-text-warning-inverse",
  danger: "border-border-danger bg-background-danger-bold text-white",
};

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
  tone?: keyof typeof ACTIVE;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-full border px-100 py-025 text-body-small",
        active ? ACTIVE[tone] : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
        className,
      )}
    >
      {children}
    </button>
  );
}
