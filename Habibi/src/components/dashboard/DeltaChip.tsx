import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  value: number; // percent
  good: "up" | "down"; // which direction is favorable
  suffix?: string;
  className?: string;
};

export function DeltaChip({ value, good, suffix = "%", className }: Props) {
  const isUp = value >= 0;
  const isGood = (isUp && good === "up") || (!isUp && good === "down");
  const Icon = isUp ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular",
        isGood ? "bg-success-bg text-success" : "bg-danger-bg text-danger",
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {Math.abs(value).toFixed(1)}
      {suffix}
    </span>
  );
}
