import { Sparkles } from "lucide-react";
import type { InsightBullet } from "@/lib/customerInsights";
import { StatusChip, type ChipTone } from "./StatusChip";

const CONF_TONE: Record<InsightBullet["confidence"], ChipTone> = {
  high: "success",
  medium: "brand",
  low: "neutral",
};

export function InsightsPanel({ bullets }: { bullets: InsightBullet[] }) {
  const list = bullets ?? [];
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-200 py-150">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" />
          AI insights
        </div>
        <span className="rounded-medium bg-background-brand-subtlest px-075 py-025 text-body-small font-semibold text-text-brand">
          Rule-derived
        </span>
      </div>
      {list.length === 0 ? (
        <div className="px-200 py-400 text-center text-body-small text-text-subtlest">
          No insights available yet.
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {list.map((b) => (
            <li key={b.id} className="px-200 py-150">
              <p className="text-body leading-snug text-text">{b.text}</p>
              <div className="mt-100 flex flex-wrap items-center gap-075">
                <span className="text-body-small text-text-subtlest">{b.source}</span>
                <StatusChip label={b.confidence} tone={CONF_TONE[b.confidence]} size="sm" />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
