import { CalendarClock, FileText, HandCoins, Mail, MapPin, PhoneCall, Sparkles, Ban, Check } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import type { Customer } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";

type Handlers = {
  onCreatePtp: () => void;
  onRaiseDispute: () => void;
  onSendStatement: () => void;
  onLogCall: () => void;
};

export function QuickActionsRail({ customer, handlers }: { customer: Customer; handlers: Handlers }) {
  const { contact, account, consent } = customer;
  return (
    <aside className="hidden w-[320px] shrink-0 flex-col overflow-hidden border-l border-border bg-surface-card xl:flex">
      <div className="flex-1 overflow-y-auto">
        <Section title="Quick actions">
          <div className="grid grid-cols-2 gap-2">
            <ActionButton icon={PhoneCall} label="Log call" onClick={handlers.onLogCall} />
            <ActionButton icon={HandCoins} label="Create PTP" onClick={handlers.onCreatePtp} primary />
            <ActionButton icon={Sparkles} label="Raise dispute" onClick={handlers.onRaiseDispute} />
            <ActionButton icon={FileText} label="Send statement" onClick={handlers.onSendStatement} />
            <ActionButton icon={CalendarClock} label="Schedule callback" onClick={() => toast.info("Opens Callback Manager — coming soon.")} className="col-span-2" />
          </div>
        </Section>

        <Section title="Contact snapshot">
          <ul className="space-y-2 text-xs">
            <Row icon={PhoneCall} value={contact.phonePrimary} sub={contact.phoneAlt ? `Alt · ${contact.phoneAlt}` : undefined} />
            <Row icon={Mail} value={contact.email} />
            <Row icon={MapPin} value={contact.address} />
            <Row icon={CalendarClock} value={contact.preferredWindow} sub={`${contact.timezone} · ${contact.language}`} />
          </ul>
        </Section>

        <Section title="Account facts">
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
            <Fact k="Product" v={account.product} />
            <Fact k="Opened" v={fmtDate(account.openedOn)} />
            <Fact k="APR" v={`${account.apr}%`} />
            <Fact k="Sanctioned" v={fmtMoney(account.sanctionedAmount)} />
            <Fact k="Bucket" v={account.bucket} />
            <Fact k="DPD" v={`${account.dpd} days`} tone={account.dpd > 60 ? "danger" : account.dpd > 30 ? "warning" : "default"} />
            <Fact k="Risk score" v={String(account.riskScore)} />
            <Fact k="Assigned" v={customer.assignedTo} />
          </dl>
        </Section>

        <Section title="Consent & channels">
          <ul className="space-y-1 text-xs">
            {consent.map((c) => (
              <li key={c.channel} className="flex items-center justify-between rounded-md border border-border bg-surface-sunken px-2.5 py-1.5">
                <span className="capitalize text-text-primary">{c.channel}</span>
                <span className={c.optedIn ? "inline-flex items-center gap-1 text-success" : "inline-flex items-center gap-1 text-danger"}>
                  {c.optedIn ? <Check className="h-3 w-3" /> : <Ban className="h-3 w-3" />}
                  {c.optedIn ? "Opted-in" : "Opted-out"}
                  <span className="ml-1 text-[10px] text-text-muted">· {c.source}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border p-4">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{title}</h3>
      {children}
    </section>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  primary,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  primary?: boolean;
  className?: string;
}) {
  return (
    <Button variant={primary ? "default" : "outline"} size="sm" onClick={onClick} className={`h-9 justify-start gap-1.5 ${className ?? ""}`}>
      <Icon className="h-3.5 w-3.5" />
      <span className="text-xs">{label}</span>
    </Button>
  );
}

function Row({ icon: Icon, value, sub }: { icon: React.ComponentType<{ className?: string }>; value: string; sub?: string }) {
  return (
    <li className="flex items-start gap-2">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-secondary" />
      <div className="min-w-0">
        <div className="truncate text-text-primary">{value}</div>
        {sub ? <div className="text-[10px] text-text-muted">{sub}</div> : null}
      </div>
    </li>
  );
}

function Fact({ k, v, tone }: { k: string; v: string; tone?: "default" | "warning" | "danger" }) {
  const toneClass = tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-brand-navy";
  return (
    <>
      <dt className="text-text-secondary">{k}</dt>
      <dd className={`font-medium tabular ${toneClass}`}>{v}</dd>
    </>
  );
}
