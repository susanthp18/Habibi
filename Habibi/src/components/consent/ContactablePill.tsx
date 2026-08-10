import { CheckCircle2, AlertTriangle, ShieldOff } from "lucide-react";
import { contactableSummary, type ConsentRecord } from "@/data/consent-seed";
import { Lozenge } from "@/components/ui/lozenge";

/* `dense` used to switch the inline padding. The Lozenge is already the compact size the
 * dense call sites wanted, so the prop is kept for source compatibility and ignored. */
export function ContactablePill({ record }: { record: ConsentRecord; dense?: boolean }) {
  const s = contactableSummary(record);
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
