import { cn } from "@/lib/utils";
import type { SlaLevel } from "@/data/workspace-seed";
import { Lozenge } from "@/components/ui/lozenge";

const LEVEL_TONE: Record<SlaLevel, "success" | "warning" | "danger"> = {
  ok: "success",
  warn: "warning",
  breach: "danger",
};

type Props = {
  level: SlaLevel;
  label: string;
  className?: string;
  size?: "sm" | "md";
};

/** Compact rectangular SLA chip — thin wrapper over Lozenge. */
export function SlaPill({ level, label, className, size = "sm" }: Props) {
  return (
    <Lozenge
      tone={LEVEL_TONE[level]}
      size={size === "md" ? "spacious" : "default"}
      title={label}
      className={cn("max-w-full", className)}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          level === "ok" && "bg-background-success-bold",
          level === "warn" && "bg-background-warning-bold",
          level === "breach" && "bg-background-danger-bold",
        )}
      />
      <span className="truncate">{label}</span>
    </Lozenge>
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
