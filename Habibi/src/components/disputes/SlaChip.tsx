import { cn } from "@/lib/utils";
import type { SlaTone } from "@/data/disputes-seed";

export function SlaChip({ tone, label }: { tone: SlaTone; label: string }) {
  const c = {
    ok: "bg-background-success-subtler text-text-success-bolder",
    warn: "bg-background-warning-subtler text-text-warning-bolder",
    breach: "bg-background-danger-subtler text-text-danger-bolder",
    done: "bg-surface-sunken text-text-subtlest",
  }[tone];
  return (
    <span className={cn("rounded px-075 py-025 text-body-small font-medium tabular-nums", c)}>
      {label}
    </span>
  );
}
