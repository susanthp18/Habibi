import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A dashed placeholder where a list has nothing to show. */
export function Empty({
  title,
  children,
  icon,
  action,
  className,
}: {
  title?: ReactNode;
  children?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-100 rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest",
        className,
      )}
    >
      {icon}
      {title && <div className="text-body font-medium text-text">{title}</div>}
      {children && <div className="mx-auto max-w-prose">{children}</div>}
      {action}
    </div>
  );
}
