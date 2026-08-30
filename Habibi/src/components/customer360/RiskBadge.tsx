import { StatusChip, riskTone } from "./StatusChip";
import type { RiskLevel } from "@/data/customer360-seed";

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  return (
    <StatusChip label={level} tone={riskTone(level)} shape="pill" size="sm" className={className} />
  );
}
