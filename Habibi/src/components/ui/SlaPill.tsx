import { cn } from "@/lib/utils";
import type { SlaLevel } from "@/data/workspace-seed";

const STYLES: Record<SlaLevel, string> = {
  ok: "border-success/25 bg-success-bg text-success",
  warn: "border-warning/35 bg-warning-bg text-warning",
  breach: "border-danger/30 bg-danger-bg text-danger",
};

type Props = {
  level: SlaLevel;
  label: string;
  className?: string;
  size?: "sm" | "md";
};

/** Compact rectangular SLA chip — not a cramped rounded-full capsule. */
export function SlaPill({ level, label, className, size = "sm" }: Props) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 border font-semibold tabular whitespace-nowrap",
        size === "sm" ? "rounded-md px-2 py-0.5 text-[11px]" : "rounded-md px-2.5 py-1 text-[12px]",
        STYLES[level],
        className,
      )}
      title={label}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          level === "ok" && "bg-success",
          level === "warn" && "bg-warning",
          level === "breach" && "bg-danger",
        )}
      />
      <span className="truncate">{label}</span>
    </span>
  );
}

/** Humanize callback “in N minutes” for badges (avoid “in 733m”). */
export function formatInMinutes(mins: number): string {
  if (mins <= 0) return "Due now";
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h >= 48) {
    const d = Math.floor(h / 24);
    const rh = h % 24;
    return rh ? `in ${d}d ${rh}h` : `in ${d}d`;
  }
  return m ? `in ${h}h ${m}m` : `in ${h}h`;
}
