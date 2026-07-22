import { FileLock2, ShieldCheck, AlertTriangle, Download, EyeOff } from "lucide-react";

interface Props {
  monthlyExports: number;
  entitiesMasked: number;
  pendingReview: number;
  totalFindings: number;
  failed: number;
}

export function RedactionStatsStrip({ monthlyExports, entitiesMasked, pendingReview, totalFindings, failed }: Props) {
  const tiles = [
    { label: "Exports (30d)",       value: monthlyExports,  icon: Download,      hint: "PDF · CSV · Audio ZIP" },
    { label: "Entities masked",     value: entitiesMasked,  icon: EyeOff,        hint: "Across all exports" },
    { label: "PII findings",        value: totalFindings,   icon: ShieldCheck,   hint: "Auto-detected in queue" },
    { label: "Pending review",      value: pendingReview,   icon: FileLock2,     hint: "Records with unreviewed PII" },
    { label: "Failed / retried",    value: failed,          icon: AlertTriangle, hint: "Last 30 days" },
  ];
  return (
    <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-[var(--border-token)] bg-surface-card px-5 py-3 md:grid-cols-5">
      {tiles.map((t) => {
        const Icon = t.icon;
        return (
          <div key={t.label} className="flex items-center gap-3 rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 py-2">
            <div className="grid h-8 w-8 place-items-center rounded-md bg-brand-tint text-brand-primary-dark">
              <Icon className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wide text-text-muted">{t.label}</div>
              <div className="text-[16px] font-semibold text-brand-navy leading-tight">{t.value}</div>
              <div className="truncate text-[10px] text-text-muted">{t.hint}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
