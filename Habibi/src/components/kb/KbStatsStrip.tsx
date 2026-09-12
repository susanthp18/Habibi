import { BookOpen, MessageSquareText, AlertTriangle, Layers, Clock, Gauge } from "lucide-react";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import { formatKbDate } from "@/lib/utils";

export type KbTab = "documents" | "faqs" | "gaps" | "test";

export function KbStatsStrip({
  docs,
  activeDocs,
  faqs,
  chunks,
  gaps,
  lastIndexed,
  avgScore,
  tab,
  onTab,
}: {
  docs: number;
  activeDocs: number;
  faqs: number;
  chunks: number;
  gaps: number;
  lastIndexed: string;
  avgScore: number;
  tab: KbTab;
  onTab: (tab: KbTab) => void;
}) {
  return (
    <MetricsStrip
      className="border-b border-border bg-surface px-200 py-150 md:grid-cols-4 xl:grid-cols-6"
      tiles={[
        {
          label: "Documents",
          value: `${activeDocs}/${docs}`,
          icon: BookOpen,
          tone: "brand",
          active: tab === "documents",
          onClick: () => onTab("documents"),
        },
        {
          label: "FAQ pairs",
          value: faqs,
          icon: MessageSquareText,
          tone: "brand",
          active: tab === "faqs",
          onClick: () => onTab("faqs"),
        },
        {
          label: "Coverage gaps",
          value: gaps,
          icon: AlertTriangle,
          tone: gaps > 0 ? "danger" : "brand",
          active: tab === "gaps",
          onClick: () => onTab("gaps"),
        },
        {
          label: "Chunks indexed",
          value: chunks.toLocaleString("en-IN"),
          icon: Layers,
          tone: "brand",
          className: "hidden xl:flex",
        },
        {
          label: "Last re-index",
          value: formatKbDate(lastIndexed, { day: "2-digit", month: "short" }),
          icon: Clock,
          tone: "brand",
          className: "hidden xl:flex",
        },
        {
          label: "Avg retrieval",
          value: avgScore.toFixed(2),
          icon: Gauge,
          tone: "brand",
          active: tab === "test",
          onClick: () => onTab("test"),
        },
      ]}
    />
  );
}
