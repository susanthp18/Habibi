import { bandColor, bandFor } from "@/data/qa-seed";
import { cn } from "@/lib/utils";

export function ScoreBand({ total, size = "md" }: { total: number; size?: "sm" | "md" | "lg" }) {
  const band = bandFor(total);
  const c = bandColor(band);
  const sizes = {
    sm: "text-body-small px-075 py-025",
    md: "text-body-small px-100 py-025",
    lg: "text-body px-150 py-050 font-semibold",
  } as const;
  return (
    <span className={cn("inline-flex items-center gap-050 rounded-full border font-medium", c.bg, c.text, c.border, sizes[size])}>
      {total.toFixed(0)}
      <span className="opacity-60">/ 100</span>
    </span>
  );
}
