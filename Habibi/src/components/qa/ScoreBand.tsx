import { bandColor, bandFor } from "@/data/qa-seed";
import { cn } from "@/lib/utils";

export function ScoreBand({ total, size = "md" }: { total: number; size?: "sm" | "md" | "lg" }) {
  const band = bandFor(total);
  const c = bandColor(band);
  const sizes = {
    sm: "text-[11px] px-1.5 py-0.5",
    md: "text-[12px] px-2 py-0.5",
    lg: "text-[14px] px-2.5 py-1 font-semibold",
  } as const;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border font-medium", c.bg, c.text, c.border, sizes[size])}>
      {total.toFixed(0)}
      <span className="opacity-60">/ 100</span>
    </span>
  );
}
