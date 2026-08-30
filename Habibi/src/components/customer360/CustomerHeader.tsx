import { Link } from "@tanstack/react-router";
import { ArrowLeft, Copy, Headphones, PhoneCall } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { RiskBadge } from "./RiskBadge";
import { ContactabilityPill } from "./ContactabilityPill";
import { StatusChip } from "./StatusChip";
import type { Customer } from "@/data/customer360-seed";
import { fmtMoney } from "@/data/customer360-seed";

function initials(name: string | null | undefined) {
  return (
    str(name)
      .split(" ")
      .map((n) => n[0])
      .filter(Boolean)
      .join("")
      .slice(0, 2)
      .toUpperCase() || "?"
  );
}

function str(value: string | null | undefined, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

export function CustomerHeader({
  customer,
  onOpenRail,
}: {
  customer: Customer;
  /** Shown on <lg when context rail is collapsed */
  onOpenRail?: () => void;
}) {
  const dpdTone =
    customer.account.dpd > 60 ? "danger" : customer.account.dpd > 30 ? "warning" : "success";

  return (
    <div className="shrink-0 border-b border-border bg-surface">
      <div className="flex items-center gap-100 border-b border-border/60 px-200 py-075 text-xs text-text-subtle sm:px-300">
        <Link to="/customers" className="inline-flex items-center gap-050 hover:text-text-brand">
          <ArrowLeft className="h-3.5 w-3.5" />
          All customers
        </Link>
        <span>/</span>
        <span className="text-text">{customer.name}</span>
        {onOpenRail ? (
          <button
            type="button"
            onClick={onOpenRail}
            className="ml-auto text-body-small font-medium text-text-brand hover:underline lg:hidden"
          >
            Context
          </button>
        ) : null}
      </div>

      <div className="grid grid-cols-1 items-center gap-200 px-200 py-150 sm:px-300 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
        {/* Identity */}
        <div className="flex min-w-0 items-center gap-150">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-background-brand-subtlest text-sm font-semibold text-text-brand">
            {initials(customer.name)}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-100">
              <h1 className="truncate heading-medium font-semibold text-text">{customer.name}</h1>
              <RiskBadge level={customer.risk} />
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(customer.accountId);
                  toast.success("Account number copied");
                }}
                className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface-sunken px-100 py-025 text-body-small font-medium text-text-subtle hover:bg-background-brand-subtlest hover:text-text-brand"
              >
                {customer.accountId}
                <Copy className="h-3 w-3" />
              </button>
              <span className="text-body-small text-text-subtlest">{customer.account.product}</span>
            </div>
            <div className="mt-075 flex flex-wrap items-center gap-075">
              <ContactabilityPill customerId={customer.id} contact={customer.contact} compact />
              <StatusChip label={`${customer.account.dpd} DPD`} tone={dpdTone} />
              <StatusChip label={customer.account.bucket} tone="neutral" />
              <span className="text-body-small text-text-subtlest">
                Assigned · {customer.assignedTo}
              </span>
            </div>
          </div>
        </div>

        {/* Financials */}
        <div className="flex items-baseline gap-200 lg:justify-end">
          <div>
            <div className="text-body-small font-semibold text-text-subtle">Outstanding</div>
            <div className="text-xl font-semibold text-text tabular sm:text-2xl">
              {fmtMoney(customer.outstanding)}
            </div>
          </div>
          <div className="border-l border-border pl-200">
            <div className="text-body-small font-semibold text-text-subtle">Min due</div>
            <div className="text-sm font-semibold text-text tabular">
              {fmtMoney(customer.minimumDue)}
            </div>
          </div>
        </div>

        {/* CTAs — one primary */}
        <div className="flex items-center gap-100 lg:justify-end">
          <Button variant="outline" size="sm" className="h-9" asChild>
            <Link to="/handoff" search={{ customerId: customer.id }}>
              <Headphones className="h-3.5 w-3.5" />
              Handoff
            </Link>
          </Button>
          <Button
            size="sm"
            className="h-9 bg-background-brand-bold hover:bg-background-brand-bold-hovered"
            onClick={() => toast.success(`Dialing ${customer.contact.phonePrimary}…`)}
          >
            <PhoneCall className="h-3.5 w-3.5" />
            Start call
          </Button>
        </div>
      </div>
    </div>
  );
}
