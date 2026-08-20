import {
  AlertOctagon,
  ExternalLink,
  HandCoins,
  MessageCircle,
  Phone,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import type { Thread } from "@/data/inbox-seed";
import { Avatar } from "./meta";
import { Lozenge } from "@/components/ui/lozenge";
import { Badge } from "@/components/ui/badge";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const promiseTone = {
  Kept: "success",
  Broken: "danger",
  Pending: "selected",
  Partial: "warning",
} as const;

export function ContextRail({
  thread,
  onClose,
}: {
  thread: Thread;
  onClose?: () => void;
}) {
  const c = thread.context;
  const navigate = useNavigate();
  const customerId = thread.customerId;
  const openDisputes = c.openDisputes.length > 0;

  const openCustomer360 = () => {
    if (!customerId) {
      toast.error("Customer id missing for this thread");
      return;
    }
    void navigate({ to: "/customers/$customerId", params: { customerId } });
  };

  const openCreatePtp = () => {
    void navigate({ to: "/promises", search: { new: true } });
    toast.message("Create PTP — select this customer if prompted");
  };

  const openRaiseDispute = () => {
    void navigate({ to: "/disputes", search: { new: true } });
    toast.message("Raise dispute — select this customer if prompted");
  };

  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-surface">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex items-center justify-between gap-100 px-200 pt-150">
          <span className="text-body-small font-semibold text-text-subtlest">Customer</span>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken hover:text-text"
              aria-label="Close customer context"
              title="Close"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="flex items-start gap-150 px-200 py-150">
          <Avatar name={thread.customer} size={40} />
          <div className="min-w-0 flex-1">
            {customerId ? (
              <Link
                to="/customers/$customerId"
                params={{ customerId }}
                className="truncate text-body font-semibold text-text hover:underline"
              >
                {thread.customer}
              </Link>
            ) : (
              <div className="truncate text-body font-semibold text-text">
                {thread.customer}
              </div>
            )}
            <div className="font-mono text-body-small text-text-subtlest">{thread.accountId}</div>
            <div className="mt-075 flex items-center gap-075 text-body-small text-text-subtle">
              {c.contactableNow ? (
                <ShieldCheck className="h-3.5 w-3.5 text-text-success" />
              ) : (
                <ShieldAlert className="h-3.5 w-3.5 text-text-danger" />
              )}
              <span>
                {c.contactableNow ? "Contactable" : "Not contactable"}
                <span className="text-text-subtlest"> · {c.contactWindow}</span>
              </span>
            </div>
            <div className="mt-050 text-body-small text-text-subtle">{c.riskLevel} risk</div>
          </div>
        </div>

        <div className="border-t border-border px-200 py-200">
          <div className="text-body-small font-semibold text-text-subtlest">Outstanding</div>
          <div className="mt-050 font-mono metric-medium text-text tabular">
            ₹{c.outstanding.toLocaleString("en-IN")}
          </div>
          <div className="text-body-small text-text-subtle">{c.outstandingAging}</div>

          <dl className="mt-150 space-y-100">
            <div className="flex items-baseline justify-between gap-100">
              <dt className="text-body-small text-text-subtlest">Next EMI</dt>
              <dd className="text-right text-body-small text-text">
                {c.nextEmiAmount ? `₹${c.nextEmiAmount.toLocaleString("en-IN")}` : "—"}
                {c.nextEmiDate ? (
                  <span className="text-text-subtlest"> · {c.nextEmiDate}</span>
                ) : null}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-100">
              <dt className="text-body-small text-text-subtlest">Last promise</dt>
              <dd className="flex min-w-0 items-center justify-end gap-075 text-body-small text-text">
                {c.lastPromise ? (
                  <>
                    <span>
                      ₹{c.lastPromise.amount.toLocaleString("en-IN")}
                      <span className="text-text-subtlest"> · {c.lastPromise.date}</span>
                    </span>
                    <Lozenge tone={promiseTone[c.lastPromise.status]}>
                      {c.lastPromise.status}
                    </Lozenge>
                  </>
                ) : (
                  <span className="text-text-subtlest">None on file</span>
                )}
              </dd>
            </div>
          </dl>
        </div>

        <Accordion
          type="multiple"
          defaultValue={openDisputes ? ["disputes"] : []}
          className="border-t border-border"
        >
          <AccordionItem value="disputes" className="border-b border-border px-200">
            <AccordionTrigger className="py-150 text-body-small font-semibold text-text hover:no-underline [&_svg]:h-3.5 [&_svg]:w-3.5">
              <span className="flex items-center gap-075">
                Open disputes
                <Badge>{c.openDisputes.length}</Badge>
              </span>
            </AccordionTrigger>
            <AccordionContent className="pb-150">
              {c.openDisputes.length === 0 ? (
                <div className="text-body-small text-text-subtle">No open disputes.</div>
              ) : (
                <ul className="space-y-075">
                  {c.openDisputes.map((d) => (
                    <li key={d.id} className="flex items-start gap-100">
                      <AlertOctagon className="mt-025 h-3.5 w-3.5 shrink-0 text-text-warning" />
                      <div className="min-w-0">
                        <div className="font-mono text-body-small text-text-subtlest">{d.id}</div>
                        <div className="text-body-small text-text">{d.summary}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="interactions" className="border-b-0 px-200">
            <AccordionTrigger className="py-150 text-body-small font-semibold text-text hover:no-underline [&_svg]:h-3.5 [&_svg]:w-3.5">
              Recent interactions
            </AccordionTrigger>
            <AccordionContent className="pb-150">
              {c.recentInteractions.length === 0 ? (
                <div className="text-body-small text-text-subtle">No recent interactions.</div>
              ) : (
                <ul className="space-y-100">
                  {c.recentInteractions.map((r) => {
                    const Icon = r.kind === "call" ? Phone : MessageCircle;
                    return (
                      <li key={r.id} className="flex items-start gap-100">
                        <Icon className="mt-025 h-3.5 w-3.5 shrink-0 text-text-subtlest" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-body-small text-text">{r.summary}</div>
                          <div className="text-body-small text-text-subtle">{r.when}</div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      <div className="shrink-0 border-t border-border px-200 py-150">
        <div className="grid grid-cols-2 gap-100">
          <button
            type="button"
            onClick={openCustomer360}
            className="focus-ring col-span-2 inline-flex items-center justify-center gap-075 rounded-medium bg-background-brand-bold px-150 py-100 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered active:scale-[0.98]"
          >
            Open Customer 360
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={openCreatePtp}
            className="focus-ring inline-flex items-center justify-center gap-075 rounded-medium border border-border bg-surface px-150 py-100 text-body-small font-medium text-text hover:bg-background-brand-subtlest hover:text-text-brand"
          >
            <HandCoins className="h-3.5 w-3.5 text-text-brand" />
            Create PTP
          </button>
          <button
            type="button"
            onClick={openRaiseDispute}
            className="focus-ring inline-flex items-center justify-center gap-075 rounded-medium border border-border bg-surface px-150 py-100 text-body-small font-medium text-text hover:bg-background-brand-subtlest hover:text-text-brand"
          >
            <AlertOctagon className="h-3.5 w-3.5 text-text-brand" />
            Raise dispute
          </button>
        </div>
      </div>
    </aside>
  );
}
