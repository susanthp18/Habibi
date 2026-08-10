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
      ? "bg-background-success text-text-success"
      : value < -0.2
        ? "bg-background-danger text-text-danger"
        : "bg-background-warning text-text-warning";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-050 rounded-full font-semibold",
        cls,
        size === "sm" ? "px-075 py-025 text-body-small" : "px-100 py-025 text-body-small",
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
