import type { LucideIcon } from "lucide-react";
import { BookOpen, MessageSquareText, AlertTriangle, Layers, Clock, Gauge } from "lucide-react";
import { cn, formatKbDate } from "@/lib/utils";

export type KbTab = "documents" | "faqs" | "gaps" | "test";

type TileProps = {
  label: string;
  value: string;
  icon: LucideIcon;
  active?: boolean;
  tone?: "default" | "danger" | "warning";
  onClick?: () => void;
  className?: string;
};

function Tile({ label, value, icon: Icon, active, tone = "default", onClick, className: extra }: TileProps) {
  const iconTone =
    tone === "danger"
      ? "bg-background-danger text-text-danger"
      : tone === "warning"
        ? "bg-background-warning text-text-warning"
        : "bg-background-brand-subtlest text-text-brand";
  const className = cn(
    "flex min-w-0 flex-1 items-center gap-150 rounded-large border bg-surface px-150 py-100 text-left",
    active ? "border-border-brand bg-background-brand-subtlest/40" : "border-border",
    onClick && "transition-colors hover:bg-surface-sunken",
    extra,
  );
  const inner = (
    <>
      <div className={cn("grid h-400 w-400 shrink-0 place-items-center rounded-medium", iconTone)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-body-small font-semibold text-text-subtlest">{label}</div>
        <div className="tabular truncate text-[1.25rem] font-semibold leading-tight text-text">{value}</div>
      </div>
    </>
  );
  if (!onClick) {
    return <div className={className}>{inner}</div>;
  }
  return (
    <button type="button" onClick={onClick} className={className} aria-pressed={active}>
      {inner}
    </button>
  );
}

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
    <div className="grid shrink-0 grid-cols-2 gap-100 border-b border-border bg-surface px-200 py-150 md:grid-cols-4 xl:grid-cols-6">
      <Tile
        label="Documents"
        value={`${activeDocs}/${docs}`}
        icon={BookOpen}
        active={tab === "documents"}
        onClick={() => onTab("documents")}
      />
      <Tile
        label="FAQ pairs"
        value={String(faqs)}
        icon={MessageSquareText}
        active={tab === "faqs"}
        onClick={() => onTab("faqs")}
      />
      <Tile
        label="Coverage gaps"
        value={String(gaps)}
        icon={AlertTriangle}
        tone={gaps > 0 ? "danger" : "default"}
        active={tab === "gaps"}
        onClick={() => onTab("gaps")}
      />
      <Tile
        label="Chunks indexed"
        value={chunks.toLocaleString("en-IN")}
        icon={Layers}
        className="hidden xl:flex"
      />
      <Tile
        label="Last re-index"
        value={formatKbDate(lastIndexed, { day: "2-digit", month: "short" })}
        icon={Clock}
        className="hidden xl:flex"
      />
      <Tile
        label="Avg retrieval"
        value={avgScore.toFixed(2)}
        icon={Gauge}
        active={tab === "test"}
        onClick={() => onTab("test")}
      />
    </div>
  );
}
