import { cn } from "@/lib/utils";
import type { IntentAgg } from "@/data/bot-analytics-seed";

function cell(value: number, max: number, tone: "pos" | "neu" | "neg"): string {
  const intensity = Math.min(1, value / (max || 1));
  const alpha = 0.1 + intensity * 0.7;
  if (tone === "pos") return `rgba(16, 185, 129, ${alpha})`;
  if (tone === "neg") return `rgba(220, 38, 38, ${alpha})`;
  return `rgba(100, 116, 139, ${alpha})`;
}

export function SentimentByIntentHeatmap({
  intents,
  activeId,
}: {
  intents: IntentAgg[];
  activeId: string | null;
}) {
  const max = Math.max(
    ...intents.flatMap((i) => [i.sentiment.positive, i.sentiment.neutral, i.sentiment.negative]),
  );
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[13px] font-semibold text-brand-navy">Sentiment × Intent</div>
        <div className="text-[11px] text-text-muted">Session counts by bucket · darker = more</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead className="bg-surface-sunken text-[11px] uppercase tracking-wide text-text-muted">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Intent</th>
              <th className="px-3 py-2 text-center font-medium">Positive</th>
              <th className="px-3 py-2 text-center font-medium">Neutral</th>
              <th className="px-3 py-2 text-center font-medium">Negative</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-token)]">
            {intents.map((i) => {
              const dim = activeId && activeId !== i.id;
              return (
                <tr key={i.id} className={cn(dim && "opacity-40", activeId === i.id && "bg-brand-tint/30")}>
                  <td className="px-3 py-1.5 font-medium text-text-primary">{i.label}</td>
                  <td className="p-1.5 text-center" style={{ background: cell(i.sentiment.positive, max, "pos") }}>{i.sentiment.positive.toLocaleString()}</td>
                  <td className="p-1.5 text-center" style={{ background: cell(i.sentiment.neutral, max, "neu") }}>{i.sentiment.neutral.toLocaleString()}</td>
                  <td className="p-1.5 text-center" style={{ background: cell(i.sentiment.negative, max, "neg") }}>{i.sentiment.negative.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
