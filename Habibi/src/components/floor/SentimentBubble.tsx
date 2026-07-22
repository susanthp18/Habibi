import { cn } from "@/lib/utils";
import { TrendingDown, TrendingUp } from "lucide-react";

type Props = {
  value: number; // -1..1
  trend?: number;
  size?: "sm" | "md";
};

export function SentimentBubble({ value, trend, size = "sm" }: Props) {
  const label =
    value > 0.25 ? "Positive" : value < -0.2 ? "Negative" : "Neutral";
  const cls =
    value > 0.25
      ? "bg-success-bg text-success"
      : value < -0.2
        ? "bg-danger-bg text-danger"
        : "bg-warning-bg text-warning";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-semibold",
        cls,
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]",
      )}
    >
      <span className="tabular">{value >= 0 ? "+" : ""}{value.toFixed(2)}</span>
      <span>· {label}</span>
      {trend !== undefined && Math.abs(trend) > 0.05 && (
        trend > 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />
      )}
    </span>
  );
}
