import {
  AlertOctagon,
  ExternalLink,
  HandCoins,
  MessageCircle,
  Phone,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread } from "@/data/inbox-seed";
import { Avatar, sentimentColor } from "./meta";
import { Badge } from "@/components/ui/badge";

const riskTone = { High: "danger", Medium: "warning", Low: "success" } as const;

const promiseTone = {
  Kept: "success",
  Broken: "danger",
  Pending: "selected",
  Partial: "warning",
} as const;

export function ContextRail({ thread }: { thread: Thread }) {
  const c = thread.context;
  const navigate = useNavigate();
  const customerId = thread.customerId;

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
    <aside className="flex h-full min-h-0 w-full flex-col gap-150 overflow-y-auto bg-surface p-150">
      <div className="rounded-xlarge border border-border bg-surface p-200">
        <div className="flex items-start gap-150">
          <Avatar name={thread.customer} size={44} />
          <div className="min-w-0">
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
            <div className="mt-075 flex flex-wrap items-center gap-075">
              <Lozenge tone={riskTone[c.riskLevel]}>{c.riskLevel} risk</Lozenge>
              <Lozenge tone={c.contactableNow ? "success" : "danger"}>
                {c.contactableNow ? <ShieldCheck /> : <ShieldAlert />}
                {c.contactableNow ? "Contactable now" : "Not contactable"}
              </Lozenge>
            </div>
            <div className="mt-050 text-body-small text-text-subtle">Window: {c.contactWindow}</div>
          </div>
        </div>
      </div>

      <div className="rounded-xlarge border border-border bg-surface p-200">
        <div className="text-body-small font-semibold text-text-subtlest">
          Outstanding
        </div>
        <div className="mt-050 font-mono metric-medium text-text tabular">
          ₹{c.outstanding.toLocaleString("en-IN")}
        </div>
        <div className="text-body-small text-text-subtle">{c.outstandingAging}</div>
      </div>

      <div className="grid grid-cols-2 gap-150">
        <div className="rounded-xlarge border border-border bg-surface p-200">
          <div className="text-body-small font-semibold text-text-subtlest">
            Next EMI
          </div>
          <div className="mt-050 font-mono text-body font-weight-bold-token text-text tabular">
            {c.nextEmiAmount ? `₹${c.nextEmiAmount.toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="text-body-small text-text-subtle">{c.nextEmiDate}</div>
        </div>
        <div className="rounded-xlarge border border-border bg-surface p-200">
          <div className="text-body-small font-semibold text-text-subtlest">
            Last promise
          </div>
          {c.lastPromise ? (
            <>
              <div className="mt-050 font-mono text-body font-weight-bold-token text-text tabular">
                ₹{c.lastPromise.amount.toLocaleString("en-IN")}
              </div>
              <div className="flex items-center gap-050 text-body-small text-text-subtle">
                <span>{c.lastPromise.date}</span>
                <Lozenge tone={promiseTone[c.lastPromise.status]} className="ml-auto">
                  {c.lastPromise.status}
                </Lozenge>
              </div>
            </>
          ) : (
            <div className="mt-050 text-body-small text-text-subtle">None on file</div>
          )}
        </div>
      </div>

      <div className="rounded-xlarge border border-border bg-surface p-200">
        <div className="mb-100 flex items-center justify-between">
          <span className="text-body-small font-semibold text-text-subtlest">
            Open disputes
          </span>
          <Badge>{c.openDisputes.length}</Badge>
        </div>
        {c.openDisputes.length === 0 ? (
          <div className="text-body-small text-text-subtle">No open disputes.</div>
        ) : (
          <ul className="space-y-075">
            {c.openDisputes.map((d) => (
              <li
                key={d.id}
                className="flex items-start gap-100 rounded-medium border border-border bg-surface-sunken px-150 py-075"
              >
                <AlertOctagon className="mt-025 h-3.5 w-3.5 shrink-0 text-text-warning" />
                <div className="min-w-0">
                  <div className="font-mono text-body-small text-text-subtlest">{d.id}</div>
                  <div className="text-body-small text-text">{d.summary}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-xlarge border border-border bg-surface p-200">
        <div className="mb-100 text-body-small font-semibold text-text-subtlest">
          Recent interactions
        </div>
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
                <span
                  className={cn(
                    "mt-050 h-100 w-100 shrink-0 rounded-full",
                    sentimentColor[r.sentiment],
                  )}
                  title={`${r.sentiment} sentiment`}
                />
              </li>
            );
          })}
        </ul>
      </div>

      <div className="rounded-xlarge border border-border bg-surface p-200">
        <div className="mb-100 text-body-small font-semibold text-text-subtlest">
          Quick actions
        </div>
        <div className="grid grid-cols-2 gap-100">
          <button
            type="button"
            onClick={openCustomer360}
            className="focus-ring col-span-2 inline-flex items-center justify-center gap-075 rounded-medium bg-background-brand-bold px-150 py-100 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered active:scale-[0.98]"
          >
            Open full Customer 360
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
