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
import type { Thread, ThreadContext } from "@/api/types/inbox";
import { Avatar } from "./Avatar";
import { closesAtWords, replyBlockedWords } from "./inbox-words";
import { Lozenge } from "@/components/ui/lozenge";
import { Badge } from "@/components/ui/badge";
import { ContactabilityPill } from "@/components/customer360/ContactabilityPill";
import { fmtMoney } from "@/lib/format";
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
  context: c,
  onClose,
  canFileRecords = false,
}: {
  thread: Thread;
  context: ThreadContext;
  onClose?: () => void;
  /** perm-collections-write: what creating a promise or a dispute needs. */
  canFileRecords?: boolean;
}) {
  const navigate = useNavigate();
  const customerId = thread.customerId;
  // Records filed from here are about this thread's loan, not the customer's first.
  const accountId = thread.accountId || undefined;
  const disputes = c.openDisputes ?? [];
  const interactions = c.recentInteractions ?? [];
  const disputeTotal = c.openDisputesTotal ?? disputes.length;

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
            <Link
              to="/customers/$customerId"
              params={{ customerId }}
              className="truncate text-body font-semibold text-text hover:underline"
            >
              {thread.customer}
            </Link>
            <div className="font-mono text-body-small text-text-subtlest">
              {thread.accountId || "No account on this thread"}
            </div>
            {/* The reply this thread's composer would send: its own channel,
                in-session inside WhatsApp's window. Not general outreach. */}
            <div className="mt-075 flex items-start gap-075 text-body-small text-text-subtle">
              {c.canReply ? (
                <ShieldCheck className="mt-025 h-3.5 w-3.5 shrink-0 text-text-success" />
              ) : (
                <ShieldAlert className="mt-025 h-3.5 w-3.5 shrink-0 text-text-danger" />
              )}
              <span>
                {c.canReply
                  ? c.replyWindowEndsAt
                    ? `Can reply until ${closesAtWords(c.replyWindowEndsAt)}`
                    : "Can reply now"
                  : replyBlockedWords(c.replyBlockedReason, thread.channel)}
                {c.replyToLast4 && (
                  <span className="block text-text-subtlest">
                    To the {c.replyToSlot === "alt" ? "alternate" : "primary"} number ending{" "}
                    {c.replyToLast4}
                  </span>
                )}
              </span>
            </div>
            <div className="mt-075 flex flex-wrap items-center gap-075">
              <span className="text-body-small text-text-subtlest">Calling</span>
              <ContactabilityPill customerId={customerId} compact />
            </div>
            <div className="mt-050 text-body-small text-text-subtle">
              {c.riskLevel} risk · window {c.contactWindow}
            </div>
          </div>
        </div>

        <div className="border-t border-border px-200 py-200">
          <div className="text-body-small font-semibold text-text-subtlest">
            Outstanding · this loan
          </div>
          <div className="mt-050 font-mono metric-medium text-text tabular">
            {c.outstanding == null ? "—" : fmtMoney(c.outstanding)}
          </div>
          <div className="text-body-small text-text-subtle">{c.outstandingAging}</div>

          <dl className="mt-150 space-y-100">
            <div className="flex items-baseline justify-between gap-100">
              <dt className="text-body-small text-text-subtlest">
                {c.nextEmiOverdue ? "Overdue EMI" : "Next EMI"}
              </dt>
              <dd
                className={
                  c.nextEmiOverdue
                    ? "text-right text-body-small text-text-danger"
                    : "text-right text-body-small text-text"
                }
              >
                {c.nextEmiAmount != null && c.nextEmiDate ? (
                  <>
                    {fmtMoney(c.nextEmiAmount)}
                    <span className="text-text-subtlest"> · {c.nextEmiDate}</span>
                  </>
                ) : (
                  <span className="text-text-subtlest">None due</span>
                )}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-100">
              <dt className="text-body-small text-text-subtlest">Last promise · any loan</dt>
              <dd className="flex min-w-0 items-center justify-end gap-075 text-body-small text-text">
                {c.lastPromise ? (
                  <>
                    <span>
                      {fmtMoney(c.lastPromise.amount)}
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
          defaultValue={disputeTotal > 0 ? ["disputes"] : []}
          className="border-t border-border"
        >
          <AccordionItem value="disputes" className="border-b border-border px-200">
            <AccordionTrigger className="py-150 text-body-small font-semibold text-text hover:no-underline [&_svg]:h-3.5 [&_svg]:w-3.5">
              <span className="flex items-center gap-075">
                Open disputes · any loan
                <Badge>{disputeTotal}</Badge>
              </span>
            </AccordionTrigger>
            <AccordionContent className="pb-150">
              {disputes.length === 0 ? (
                <div className="text-body-small text-text-subtle">No open disputes.</div>
              ) : (
                <ul className="space-y-075">
                  {disputes.map((d) => (
                    <li key={d.id} className="flex items-start gap-100">
                      <AlertOctagon className="mt-025 h-3.5 w-3.5 shrink-0 text-text-warning" />
                      <div className="min-w-0">
                        <Link
                          to="/disputes"
                          search={{ id: d.id }}
                          className="font-mono text-body-small text-text-brand hover:underline"
                        >
                          {d.id}
                        </Link>
                        <div className="text-body-small text-text">{d.summary}</div>
                      </div>
                    </li>
                  ))}
                  {disputeTotal > disputes.length && (
                    <li className="text-body-small text-text-subtle">
                      Newest {disputes.length} of {disputeTotal} —{" "}
                      <Link
                        to="/customers/$customerId"
                        params={{ customerId }}
                        className="text-text-brand hover:underline"
                      >
                        see all in Customer 360
                      </Link>
                    </li>
                  )}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="interactions" className="border-b-0 px-200">
            <AccordionTrigger className="py-150 text-body-small font-semibold text-text hover:no-underline [&_svg]:h-3.5 [&_svg]:w-3.5">
              Recent interactions · any loan
            </AccordionTrigger>
            <AccordionContent className="pb-150">
              {interactions.length === 0 ? (
                <div className="text-body-small text-text-subtle">No recent interactions.</div>
              ) : (
                <ul className="space-y-100">
                  {interactions.map((r) => {
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
                  <li>
                    <Link
                      to="/customers/$customerId"
                      params={{ customerId }}
                      className="text-body-small text-text-brand hover:underline"
                    >
                      Full history in Customer 360
                    </Link>
                  </li>
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
            onClick={() => void navigate({ to: "/customers/$customerId", params: { customerId } })}
            className="focus-ring col-span-2 inline-flex items-center justify-center gap-075 rounded-medium bg-background-brand-bold px-150 py-100 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered active:scale-[0.98]"
          >
            Open Customer 360
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          {/* Offered only to someone who can file them: the form opened for
              anyone, and refused at the very end. */}
          {canFileRecords && (
            <button
              type="button"
              onClick={() =>
                void navigate({ to: "/promises", search: { new: true, customerId, accountId } })
              }
              className="focus-ring inline-flex items-center justify-center gap-075 rounded-medium border border-border bg-surface px-150 py-100 text-body-small font-medium text-text hover:bg-background-brand-subtlest hover:text-text-brand"
            >
              <HandCoins className="h-3.5 w-3.5 text-text-brand" />
              Create PTP
            </button>
          )}
          {canFileRecords && (
            <button
              type="button"
              onClick={() =>
                void navigate({ to: "/disputes", search: { new: true, customerId, accountId } })
              }
              className="focus-ring inline-flex items-center justify-center gap-075 rounded-medium border border-border bg-surface px-150 py-100 text-body-small font-medium text-text hover:bg-background-brand-subtlest hover:text-text-brand"
            >
              <AlertOctagon className="h-3.5 w-3.5 text-text-brand" />
              Raise dispute
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
