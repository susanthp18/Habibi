import { CheckCircle2, AlertTriangle, ShieldOff } from "lucide-react";
import type { ConsentRecord } from "@/api/types/consent";
import { Lozenge } from "@/components/ui/lozenge";

export function ContactablePill({ record }: { record: ConsentRecord }) {
  const s = record.contactable;
  const map = {
    green: { tone: "success", Icon: CheckCircle2, label: "Contactable" },
    amber: { tone: "warning", Icon: AlertTriangle, label: "Partial" },
    red: { tone: "danger", Icon: ShieldOff, label: "Blocked" },
  }[s.status];
  return (
    <Lozenge tone={map.tone as "success" | "warning" | "danger"} title={s.reasons.join(" · ")}>
      <map.Icon />
      {map.label}
    </Lozenge>
  );
}
