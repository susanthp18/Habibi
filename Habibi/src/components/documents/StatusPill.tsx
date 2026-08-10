import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { STATUS_LABELS, type DocStatus } from "@/data/documents-seed";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";

const TONE: Record<DocStatus, NonNullable<LozengeProps["tone"]>> = {
  requested: "information",
  generating: "warning",
  sent: "success",
  failed: "danger",
};

const ICON = {
  requested: Clock,
  generating: Loader2,
  sent: CheckCircle2,
  failed: XCircle,
} as const;

/** Document status indicator — thin wrapper over Lozenge. */
export function StatusPill({ status, className }: { status: DocStatus; className?: string }) {
  const Icon = ICON[status];
  return (
    <Lozenge tone={TONE[status]} className={cn("rounded-full", className)}>
      <Icon className={cn("h-3 w-3", status === "generating" && "animate-spin")} />
      {STATUS_LABELS[status]}
    </Lozenge>
  );
}
