import { cn } from "@/lib/utils";
import type { RiskLevel } from "@/data/customer360-seed";

const styles: Record<RiskLevel, string> = {
  critical: "bg-danger-bg text-danger border-danger/20",
  high: "bg-warning-bg text-warning border-warning/20",
  medium: "bg-brand-tint text-brand-primary-dark border-brand-primary/20",
  low: "bg-success-bg text-success border-success/20",
};

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        styles[level],
        className,
      )}
    >
      {level}
    </span>
  );
}
