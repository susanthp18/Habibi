import { Ban, CheckCircle2, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Consent, Contact } from "@/data/customer360-seed";

type Props = { consent: Consent[]; contact: Contact; className?: string };

function withinWindow(pref: string): boolean {
  // pref format "10:00–19:00 IST"
  const m = pref.match(/(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})/);
  if (!m) return true;
  const start = Number(m[1]) * 60 + Number(m[2]);
  const end = Number(m[3]) * 60 + Number(m[4]);
  const now = new Date();
  const cur = now.getHours() * 60 + now.getMinutes();
  return cur >= start && cur <= end;
}

export function ContactabilityPill({ consent, contact, className }: Props) {
  const callOptedIn = consent.find((c) => c.channel === "call")?.optedIn ?? false;
  const inWindow = withinWindow(contact.preferredWindow);
  const dnd = contact.dnd;

  let tone: "ok" | "warn" | "bad" = "ok";
  let label = "OK to contact";
  let icon = <CheckCircle2 className="h-3.5 w-3.5" />;
  let sub = `Voice window · ${contact.preferredWindow}`;

  if (dnd || !callOptedIn) {
    tone = "bad";
    label = dnd ? "DND active" : "Voice opt-out";
    icon = <Ban className="h-3.5 w-3.5" />;
    sub = "Use WhatsApp / Email only";
  } else if (!inWindow) {
    tone = "warn";
    label = "Outside contact window";
    icon = <Clock className="h-3.5 w-3.5" />;
    sub = `Next allowed · ${contact.preferredWindow}`;
  }

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium",
        tone === "ok" && "bg-success-bg text-success border-success/20",
        tone === "warn" && "bg-warning-bg text-warning border-warning/20",
        tone === "bad" && "bg-danger-bg text-danger border-danger/20",
        className,
      )}
      title={sub}
    >
      {icon}
      <span>{label}</span>
      <span className="text-[10px] font-normal opacity-80">· {sub}</span>
    </div>
  );
}
