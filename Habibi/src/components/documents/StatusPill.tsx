import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { STATUS_LABELS, type DocStatus } from "@/data/documents-seed";

const TONE: Record<DocStatus, string> = {
  requested: "bg-brand-tint text-brand-primary-dark",
  generating: "bg-amber-100 text-amber-800",
  sent: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-700",
};

const ICON = {
  requested: Clock,
  generating: Loader2,
  sent: CheckCircle2,
  failed: XCircle,
} as const;

export function StatusPill({ status, className }: { status: DocStatus; className?: string }) {
  const Icon = ICON[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold",
        TONE[status],
        className,
      )}
    >
      <Icon className={cn("h-3 w-3", status === "generating" && "animate-spin")} />
      {STATUS_LABELS[status]}
    </span>
  );
}
