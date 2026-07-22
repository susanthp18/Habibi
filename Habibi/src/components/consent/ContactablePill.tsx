import { CheckCircle2, AlertTriangle, ShieldOff } from "lucide-react";
import { contactableSummary, type ConsentRecord } from "@/data/consent-seed";

export function ContactablePill({ record, dense }: { record: ConsentRecord; dense?: boolean }) {
  const s = contactableSummary(record);
  const map = {
    green: { bg: "var(--success-bg)", fg: "var(--success)", Icon: CheckCircle2, label: "Contactable" },
    amber: { bg: "var(--warning-bg)", fg: "var(--warning)", Icon: AlertTriangle, label: "Partial" },
    red: { bg: "var(--danger-bg)", fg: "var(--danger)", Icon: ShieldOff, label: "Blocked" },
  }[s.status];
  const title = s.reasons.join(" · ");
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full ${dense ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]"} font-semibold`}
      style={{ background: map.bg, color: map.fg }}
    >
      <map.Icon className={dense ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {map.label}
    </span>
  );
}
