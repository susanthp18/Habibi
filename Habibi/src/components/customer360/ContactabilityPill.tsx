import { Ban, CheckCircle2, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Consent, Contact } from "@/data/customer360-seed";
import { StatusChip, type ChipTone } from "./StatusChip";

type Props = { consent: Consent[]; contact: Contact; className?: string; compact?: boolean };

function withinWindow(pref: string | null | undefined): boolean {
  const m = (pref || "").match(/(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})/);
  if (!m) return true;
  const start = Number(m[1]) * 60 + Number(m[2]);
  const end = Number(m[3]) * 60 + Number(m[4]);
  const now = new Date();
  const cur = now.getHours() * 60 + now.getMinutes();
  return cur >= start && cur <= end;
}

export function contactabilityState(consent: Consent[], contact: Contact) {
  const callOptedIn = consent.find((c) => c.channel === "call")?.optedIn ?? false;
  const inWindow = withinWindow(contact.preferredWindow);
  const dnd = contact.dnd;

  let tone: ChipTone = "success";
  let label = "OK to contact";
  let sub = `Voice window · ${contact.preferredWindow}`;

  if (dnd || !callOptedIn) {
    tone = "danger";
    label = dnd ? "DND active" : "Voice opt-out";
    sub = "Use WhatsApp / Email only";
  } else if (!inWindow) {
    tone = "warning";
    label = "Outside contact window";
    sub = `Next allowed · ${contact.preferredWindow}`;
  }

  return { tone, label, sub, ok: tone === "success" };
}

export function ContactabilityPill({ consent, contact, className, compact }: Props) {
  const { tone, label, sub } = contactabilityState(consent, contact);
  const icon =
    tone === "danger" ? (
      <Ban className="h-3 w-3 shrink-0" />
    ) : tone === "warning" ? (
      <Clock className="h-3 w-3 shrink-0" />
    ) : (
      <CheckCircle2 className="h-3 w-3 shrink-0" />
    );

  return (
    <StatusChip
      label={compact ? label : `${label} · ${sub}`}
      tone={tone}
      shape="pill"
      size="sm"
      title={sub}
      className={cn("normal-case tracking-normal", className)}
    >
      {icon}
    </StatusChip>
  );
}
