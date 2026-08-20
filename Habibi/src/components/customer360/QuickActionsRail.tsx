import type { ComponentType, ReactNode } from "react";
import {
  CalendarClock,
  FileText,
  HandCoins,
  Mail,
  MapPin,
  PhoneCall,
  Scale,
  Ban,
  Check,
  PanelRight,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import type { Customer } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import type { NbaItem, NbaActionKind } from "@/lib/customerInsights";
import { StatusChip, ptpStatusTone, disputeStatusTone } from "./StatusChip";
import { cn } from "@/lib/utils";

type Handlers = {
  onCreatePtp: () => void;
  onRaiseDispute: () => void;
  onSendStatement: () => void;
  onLogCall: () => void;
  onNbaAction?: (action: NbaActionKind) => void;
};

export function QuickActionsRail({
  customer,
  handlers,
  nba = [],
  className,
}: {
  customer: Customer;
  handlers: Handlers;
  nba?: NbaItem[];
  className?: string;
}) {
  const { contact, account, consent } = customer;
  const openPtp = customer.promises.filter((p) => p.status === "upcoming");
  const openDisputes = customer.disputes.filter((d) => d.status !== "resolved" && d.status !== "rejected");

  const runAction = (action: NbaActionKind) => {
    if (handlers.onNbaAction) {
      handlers.onNbaAction(action);
      return;
    }
    if (action === "ptp") handlers.onCreatePtp();
    else if (action === "dispute" || action === "review") handlers.onRaiseDispute();
    else if (action === "statement") handlers.onSendStatement();
    else if (action === "call") handlers.onLogCall();
    else toast.info("Opens Callback Manager — coming soon.");
  };

  const ranked = nba.length
    ? nba
    : ([
        { id: "qa-ptp", rank: 1, title: "Create PTP", reason: "", action: "ptp" as const, priority: "medium" as const },
        { id: "qa-call", rank: 2, title: "Log call", reason: "", action: "call" as const, priority: "medium" as const },
        { id: "qa-dispute", rank: 3, title: "Raise dispute", reason: "", action: "dispute" as const, priority: "low" as const },
        { id: "qa-stmt", rank: 4, title: "Send statement", reason: "", action: "statement" as const, priority: "low" as const },
      ] satisfies NbaItem[]);

  return (
    <aside className={cn("flex h-full min-h-0 flex-col overflow-hidden border-l border-border bg-surface", className)}>
      <div className="flex items-center gap-100 border-b border-border px-200 py-150">
        <PanelRight className="h-3.5 w-3.5 text-text-brand" />
        <h2 className="text-[0.875rem] font-semibold text-text">Context</h2>
      </div>

      <div className="flex-1 overflow-y-auto">
        <Section title="Recommended actions">
          <div className="space-y-075">
            {ranked.slice(0, 4).map((item, i) => (
              <Button
                key={item.id}
                variant={i === 0 ? "default" : "outline"}
                size="sm"
                className={cn(
                  "h-9 w-full justify-start gap-100 text-xs",
                  i === 0 && "bg-background-brand-bold hover:bg-background-brand-bold-hovered",
                )}
                onClick={() => runAction(item.action)}
              >
                <ActionIcon action={item.action} />
                <span className="truncate">{item.title}</span>
              </Button>
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="h-400 w-full justify-start gap-100 text-xs text-text-subtle"
              onClick={() => toast.info("Opens Callback Manager — coming soon.")}
            >
              <CalendarClock className="h-3.5 w-3.5" />
              Schedule callback
            </Button>
          </div>
        </Section>

        {(openPtp.length > 0 || openDisputes.length > 0) && (
          <Section title="Open items">
            <div className="space-y-100">
              {openPtp.slice(0, 2).map((p) => (
                <div key={p.id} className="rounded-medium border border-border bg-surface-sunken px-150 py-100">
                  <div className="flex items-center justify-between gap-100">
                    <span className="text-body-small font-semibold tabular text-text">{fmtMoney(p.amount)}</span>
                    <StatusChip label={p.status} tone={ptpStatusTone(p.status)} />
                  </div>
                  <div className="mt-025 text-body-small text-text-subtlest">Due {fmtDate(p.promisedDate)}</div>
                </div>
              ))}
              {openDisputes.slice(0, 2).map((d) => (
                <div key={d.id} className="rounded-medium border border-border bg-surface-sunken px-150 py-100">
                  <div className="flex items-center justify-between gap-100">
                    <span className="truncate text-body-small font-medium text-text">{d.id}</span>
                    <StatusChip label={d.status.replace(/_/g, " ")} tone={disputeStatusTone(d.status)} />
                  </div>
                  <div className="mt-025 text-body-small text-text-subtlest tabular">{fmtMoney(d.amount)}</div>
                </div>
              ))}
            </div>
          </Section>
        )}

        <Section title="Contact snapshot">
          <ul className="space-y-100 text-xs">
            <Row icon={PhoneCall} value={contact.phonePrimary} sub={contact.phoneAlt ? `Alt · ${contact.phoneAlt}` : undefined} />
            <Row icon={Mail} value={contact.email} />
            <Row icon={MapPin} value={contact.address} />
            <Row icon={CalendarClock} value={contact.preferredWindow} sub={`${contact.timezone} · ${contact.language}`} />
          </ul>
        </Section>

        <Section title="Account facts">
          <dl className="grid grid-cols-2 gap-x-150 gap-y-100 text-xs">
            <Fact k="Product" v={account.product} />
            <Fact k="Opened" v={fmtDate(account.openedOn)} />
            <Fact k="APR" v={account.apr != null ? `${account.apr}%` : "—"} />
            <Fact k="Sanctioned" v={fmtMoney(account.sanctionedAmount)} />
            <Fact k="Bucket" v={account.bucket || "—"} />
            <Fact
              k="DPD"
              v={`${account.dpd ?? 0} days`}
              tone={(account.dpd ?? 0) > 60 ? "danger" : (account.dpd ?? 0) > 30 ? "warning" : "default"}
            />
            <Fact k="Risk score" v={account.riskScore != null ? String(account.riskScore) : "—"} />
            <Fact k="Assigned" v={customer.assignedTo} />
          </dl>
        </Section>

        <Section title="Consent & channels">
          <ul className="space-y-050 text-xs">
            {consent.map((c) => (
              <li
                key={c.channel}
                className="flex items-center justify-between rounded-medium border border-border bg-surface-sunken px-150 py-075"
              >
                <span className="capitalize text-text">{c.channel}</span>
                <span className={c.optedIn ? "inline-flex items-center gap-050 text-text-success" : "inline-flex items-center gap-050 text-text-danger"}>
                  {c.optedIn ? <Check className="h-3 w-3" /> : <Ban className="h-3 w-3" />}
                  {c.optedIn ? "In" : "Out"}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </aside>
  );
}

function ActionIcon({ action }: { action: NbaActionKind }) {
  const cls = "h-3.5 w-3.5";
  if (action === "ptp") return <HandCoins className={cls} />;
  if (action === "dispute" || action === "review") return <Scale className={cls} />;
  if (action === "statement") return <FileText className={cls} />;
  if (action === "callback") return <CalendarClock className={cls} />;
  if (action === "offer") return <Sparkles className={cls} />;
  return <PhoneCall className={cls} />;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-border p-200">
      <h3 className="mb-100 text-body-small font-semibold text-text-subtle">{title}</h3>
      {children}
    </section>
  );
}

function Row({ icon: Icon, value, sub }: { icon: ComponentType<{ className?: string }>; value: string; sub?: string }) {
  return (
    <li className="flex items-start gap-100">
      <Icon className="mt-025 h-3.5 w-3.5 shrink-0 text-text-subtle" />
      <div className="min-w-0">
        <div className="truncate text-text">{value}</div>
        {sub ? <div className="text-body-small text-text-subtlest">{sub}</div> : null}
      </div>
    </li>
  );
}

function Fact({ k, v, tone }: { k: string; v: string; tone?: "default" | "warning" | "danger" }) {
  const toneClass = tone === "danger" ? "text-text-danger" : tone === "warning" ? "text-text-warning" : "text-text";
  return (
    <>
      <dt className="text-text-subtle">{k}</dt>
      <dd className={`font-medium tabular ${toneClass}`}>{v}</dd>
    </>
  );
}
