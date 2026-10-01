import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

/** Matches workspace queue SLA. Local so `components/ui` does not import `api/`. */
type SlaLevel = "ok" | "warn" | "breach";

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
