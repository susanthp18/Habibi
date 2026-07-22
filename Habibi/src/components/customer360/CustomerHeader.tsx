import { Link } from "@tanstack/react-router";
import { ArrowLeft, Copy, Headphones, PhoneCall } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { RiskBadge } from "./RiskBadge";
import { ContactabilityPill } from "./ContactabilityPill";
import type { Customer } from "@/data/customer360-seed";
import { fmtMoney } from "@/data/customer360-seed";

function initials(name: string) {
  return name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();
}

export function CustomerHeader({ customer }: { customer: Customer }) {
  return (
    <div className="shrink-0 border-b border-border bg-surface-card">
      <div className="flex items-center gap-2 border-b border-border/60 px-6 py-2 text-xs text-text-secondary">
        <Link to="/customers" className="inline-flex items-center gap-1 hover:text-brand-primary">
          <ArrowLeft className="h-3.5 w-3.5" />
          All customers
        </Link>
        <span>/</span>
        <span className="text-text-primary">{customer.name}</span>
      </div>

      <div className="flex flex-wrap items-start gap-4 px-6 py-4">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-tint text-lg font-semibold text-brand-primary-dark">
          {initials(customer.name)}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-brand-navy">{customer.name}</h1>
            <RiskBadge level={customer.risk} />
            <button
              onClick={() => {
                navigator.clipboard.writeText(customer.accountId);
                toast.success("Account number copied");
              }}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-sunken px-2 py-0.5 text-xs font-medium text-text-secondary hover:bg-brand-tint hover:text-brand-primary-dark"
            >
              {customer.accountId}
              <Copy className="h-3 w-3" />
            </button>
            <span className="text-xs text-text-secondary">· {customer.account.product}</span>
            <span className="text-xs text-text-secondary">· {customer.contact.phonePrimary}</span>
          </div>
          <div className="mt-2">
            <ContactabilityPill consent={customer.consent} contact={customer.contact} />
          </div>
        </div>

        <div className="text-right">
          <div className="text-[11px] uppercase tracking-wide text-text-secondary">Outstanding</div>
          <div className="text-2xl font-semibold text-brand-navy tabular">{fmtMoney(customer.outstanding)}</div>
          <div className="text-xs text-text-muted tabular">Min due · {fmtMoney(customer.minimumDue)}</div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => toast.info("Opens Handoff Hub for this account.")}>
            <Headphones className="h-3.5 w-3.5" />
            Handoff
          </Button>
          <Button size="sm" onClick={() => toast.success(`Dialing ${customer.contact.phonePrimary}…`)}>
            <PhoneCall className="h-3.5 w-3.5" />
            Start call
          </Button>
        </div>
      </div>
    </div>
  );
}
