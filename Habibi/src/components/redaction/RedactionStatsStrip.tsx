import { FileLock2, ShieldCheck, AlertTriangle, Download, EyeOff } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";

interface Props {
  monthlyExports: number;
  entitiesMasked: number;
  pendingReview: number;
  totalFindings: number;
  failed: number;
  /** Export tiles are seed-backed until export-jobs endpoints land. */
  seedExports?: boolean;
}

export function RedactionStatsStrip({
  monthlyExports,
  entitiesMasked,
  pendingReview,
  totalFindings,
  failed,
  seedExports = false,
}: Props) {
  const tiles = [
    { label: "Exports (30d)", value: monthlyExports, icon: Download, hint: "PDF · CSV · Audio ZIP", seed: seedExports },
    { label: "Entities masked", value: entitiesMasked, icon: EyeOff, hint: "Across all exports", seed: seedExports },
    { label: "PII findings", value: totalFindings, icon: ShieldCheck, hint: "Auto-detected in queue", seed: false },
    { label: "Pending review", value: pendingReview, icon: FileLock2, hint: "Records with unreviewed PII", seed: false },
    { label: "Failed / retried", value: failed, icon: AlertTriangle, hint: "Last 30 days", seed: seedExports },
  ];
  return (
    <div className="grid shrink-0 grid-cols-2 gap-100 border-b border-border bg-surface px-250 py-150 md:grid-cols-5">
      {tiles.map((t) => {
        const Icon = t.icon;
        return (
          <div key={t.label} className="flex items-center gap-150 rounded-medium border border-border bg-surface-sunken px-150 py-100">
            <div className="grid h-400 w-400 place-items-center rounded-medium bg-background-brand-subtlest text-text-brand">
              <Icon className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-075 text-body-small text-text-subtlest">
                {t.label}
                {t.seed && (
                  <Lozenge
                    title="Seed data — export jobs not yet wired to the live backend" tone="neutral" className="tracking-normal">
                    seed
                  </Lozenge>
                )}
              </div>
              <div className="text-[1rem] font-semibold text-text leading-tight">{t.value}</div>
              <div className="truncate text-body-small text-text-subtlest">{t.hint}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
