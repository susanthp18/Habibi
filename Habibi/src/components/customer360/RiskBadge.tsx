import { StatusChip, riskTone } from "./StatusChip";
import type { RiskLevel } from "@/api/types/customer360";

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  return (
    <StatusChip label={level} tone={riskTone(level)} shape="pill" size="sm" className={className} />
  );
}
