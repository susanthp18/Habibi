import type { LucideIcon } from "lucide-react";
import { BookOpen, MessageSquareText, AlertTriangle, Layers, Clock, Gauge } from "lucide-react";

interface Stat {
  label: string;
  value: string | number;
  hint?: string;
  Icon: LucideIcon;
}

export function KbStatsStrip({
  docs,
  activeDocs,
  faqs,
  chunks,
  gaps,
  lastIndexed,
  avgScore,
}: {
  docs: number;
  activeDocs: number;
  faqs: number;
  chunks: number;
  gaps: number;
  lastIndexed: string;
  avgScore: number;
}) {
  const stats: Stat[] = [
    { label: "Documents", value: `${activeDocs}/${docs}`, hint: "active / total", Icon: BookOpen },
    { label: "FAQ pairs", value: faqs, hint: "enabled", Icon: MessageSquareText },
    { label: "Chunks indexed", value: chunks.toLocaleString(), hint: "across enabled docs", Icon: Layers },
    { label: "Coverage gaps", value: gaps, hint: "from analytics", Icon: AlertTriangle },
    {
      label: "Last re-index",
      value: new Date(lastIndexed).toLocaleDateString(undefined, { day: "2-digit", month: "short" }),
      hint: "most recent doc",
      Icon: Clock,
    },
    { label: "Avg retrieval score", value: avgScore.toFixed(2), hint: "top-1 cosine", Icon: Gauge },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {stats.map((s) => (
        <div
          key={s.label}
          className="rounded-lg border border-[var(--border-token)] bg-surface-card p-3"
        >
          <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-text-muted">
            <s.Icon className="h-3.5 w-3.5" />
            {s.label}
          </div>
          <div className="mt-1.5 text-lg font-semibold text-brand-navy">{s.value}</div>
          {s.hint && <div className="text-[11px] text-text-muted">{s.hint}</div>}
        </div>
      ))}
    </div>
  );
}
