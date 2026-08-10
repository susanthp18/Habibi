import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  value: number | null; // percent; null = no prior period to compare against
  good: "up" | "down"; // which direction is favorable
  suffix?: string;
  className?: string;
};

/** Directional delta indicator — thin wrapper over Lozenge. */
export function DeltaChip({ value, good, suffix = "%", className }: Props) {
  // No comparable prior period. Render nothing rather than a green "0.0%",
  // which reads as "unchanged" — a claim we cannot make.
  if (value == null || !Number.isFinite(value)) return null;
  const isUp = value >= 0;
  const isGood = (isUp && good === "up") || (!isUp && good === "down");
  const Icon = isUp ? ArrowUpRight : ArrowDownRight;
  return (
    <Lozenge tone={isGood ? "success" : "danger"} className={cn("rounded-full tabular", className)}>
      <Icon className="h-3 w-3" />
      {Math.abs(value).toFixed(1)}
      {suffix}
    </Lozenge>
  );
}
