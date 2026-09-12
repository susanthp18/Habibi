import { FileLock2, ShieldCheck, AlertTriangle, Download, EyeOff } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";
import { MetricsStrip } from "@/components/records/MetricsStrip";

interface Props {
  monthlyExports: number;
  entitiesMasked: number;
  pendingReview: number;
  totalFindings: number;
  failed: number;
  /** Export tiles are seed-backed until export-jobs endpoints land. */
  seedExports?: boolean;
}

const SEED = (
  <Lozenge
    title="Seed data — export jobs not yet wired to the live backend"
    tone="neutral"
    className="tracking-normal"
  >
    seed
  </Lozenge>
);

export function RedactionStatsStrip({
  monthlyExports,
  entitiesMasked,
  pendingReview,
  totalFindings,
  failed,
  seedExports = false,
}: Props) {
  const seed = seedExports ? SEED : undefined;
  return (
    <MetricsStrip
      className="border-b border-border bg-surface px-250 py-150 md:grid-cols-5"
      tiles={[
        {
          label: "Exports (30d)",
          value: monthlyExports,
          icon: Download,
          tone: "brand",
          sub: "PDF · CSV · Audio ZIP",
          badge: seed,
        },
        {
          label: "Entities masked",
          value: entitiesMasked,
          icon: EyeOff,
          tone: "brand",
          sub: "Across all exports",
          badge: seed,
        },
        {
          label: "PII findings",
          value: totalFindings,
          icon: ShieldCheck,
          tone: "brand",
          sub: "Auto-detected in queue",
        },
        {
          label: "Pending review",
          value: pendingReview,
          icon: FileLock2,
          tone: "brand",
          sub: "Records with unreviewed PII",
        },
        {
          label: "Failed / retried",
          value: failed,
          icon: AlertTriangle,
          tone: "brand",
          sub: "Last 30 days",
          badge: seed,
        },
      ]}
    />
  );
}
