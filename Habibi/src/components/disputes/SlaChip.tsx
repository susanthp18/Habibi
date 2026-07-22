import { cn } from "@/lib/utils";
import type { SlaTone } from "@/data/disputes-seed";

export function SlaChip({ tone, label }: { tone: SlaTone; label: string }) {
  const c = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    breach: "bg-red-50 text-red-700",
    done: "bg-surface-sunken text-text-muted",
  }[tone];
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10.5px] font-medium tabular-nums", c)}>
      {label}
    </span>
  );
}
