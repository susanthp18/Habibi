import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** The tones a figure can carry; each maps to one token pair. */
export type StatTone =
  "brand" | "warning" | "success" | "danger" | "info" | "discovery" | "neutral";

const WELL: Record<StatTone, string> = {
  brand: "text-text-brand bg-background-brand-subtlest",
  warning: "text-text-warning-bolder bg-background-warning-subtler",
  success: "text-text-success-bolder bg-background-success-subtler",
  danger: "text-text-danger-bolder bg-background-danger-subtler",
  info: "text-text-information-bolder bg-background-information-subtler",
  discovery: "text-text-discovery bg-background-discovery-subtler",
  neutral: "text-text-subtle bg-surface-sunken",
};

const TEXT: Record<StatTone, string> = {
  brand: "text-text-brand",
  warning: "text-text-warning-bolder",
  success: "text-text-success-bolder",
  danger: "text-text-danger-bolder",
  info: "text-text-information-bolder",
  discovery: "text-text-discovery",
  neutral: "text-text-subtle",
};

export interface StatTileProps {
  label: string;
  value: ReactNode;
  /** A second line under the figure: a subtotal, a window, a hint. */
  sub?: ReactNode;
  icon?: LucideIcon;
  tone?: StatTone;
  /** Beside the label: a lozenge, a live dot. */
  badge?: ReactNode;
  /** Under the figure: a sparkline, a bar, a delta chip. */
  footer?: ReactNode;
  /** `row` puts the icon in a toned well beside the figure; `card` stacks label, figure and footer. */
  variant?: "row" | "card";
  /** With `onClick` the tile is a pressable filter; `active` is its pressed state. */
  active?: boolean;
  onClick?: () => void;
  className?: string;
}

/**
 * One figure with a label, and optionally an icon, a sub line, a badge and a
 * footer. Fifteen strips each declared a tile of their own, with five tone
 * vocabularies for the same five colours.
 */
export function StatTile({
  label,
  value,
  sub,
  icon: Icon,
  tone = "neutral",
  badge,
  footer,
  variant = "row",
  active,
  onClick,
  className,
}: StatTileProps) {
  const shell = cn(
    "min-w-0 rounded-large border bg-surface text-left",
    variant === "row" ? "flex items-center gap-100 px-150 py-100" : "flex flex-col p-150",
    active ? "border-border-brand bg-background-brand-subtlest/40" : "border-border",
    onClick && "transition-colors hover:bg-surface-sunken",
    className,
  );
  const inner =
    variant === "row" ? (
      <>
        {Icon && (
          <div
            className={cn(
              "grid h-400 w-400 shrink-0 place-items-center rounded-medium",
              WELL[tone],
            )}
          >
            <Icon className="h-4 w-4" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-075 text-body-small text-text-subtlest">
            <span className="truncate">{label}</span>
            {badge}
          </div>
          <div className="truncate text-body font-semibold leading-tight text-text tabular-nums">
            {value}
          </div>
          {sub && <div className="truncate text-body-small text-text-subtlest">{sub}</div>}
          {footer}
        </div>
      </>
    ) : (
      <>
        <div className="flex items-center gap-075 text-body-small font-medium text-text-subtlest">
          <span className="truncate">{label}</span>
          {badge}
          {Icon && <Icon className={cn("ml-auto h-3.5 w-3.5 shrink-0", TEXT[tone])} />}
        </div>
        <div
          className={cn(
            "mt-025 heading-large font-semibold leading-tight tabular-nums",
            tone === "neutral" ? "text-text" : TEXT[tone],
          )}
        >
          {value}
        </div>
        {sub && <div className="text-body-small text-text-subtlest">{sub}</div>}
        {footer && <div className="mt-075">{footer}</div>}
      </>
    );
  if (!onClick) return <div className={shell}>{inner}</div>;
  return (
    <button type="button" onClick={onClick} className={shell} aria-pressed={active}>
      {inner}
    </button>
  );
}
