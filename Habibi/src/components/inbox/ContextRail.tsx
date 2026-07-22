import {
  AlertOctagon,
  ExternalLink,
  HandCoins,
  MessageCircle,
  Phone,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread } from "@/data/inbox-seed";
import { Avatar, sentimentColor } from "./meta";

const riskStyle = {
  High: "bg-danger-bg text-danger",
  Medium: "bg-warning-bg text-warning",
  Low: "bg-success-bg text-success",
} as const;

const promiseStyle = {
  Kept: "bg-success-bg text-success",
  Broken: "bg-danger-bg text-danger",
  Pending: "bg-brand-tint text-brand-primary-dark",
  Partial: "bg-warning-bg text-warning",
} as const;

export function ContextRail({ thread }: { thread: Thread }) {
  const c = thread.context;

  return (
    <aside className="hidden min-h-0 w-[300px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-[var(--border-token)] bg-surface-app p-3 xl:flex xl:w-[320px]">
      {/* Header */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <div className="flex items-start gap-3">
          <Avatar name={thread.customer} size={44} />
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold text-brand-navy">
              {thread.customer}
            </div>
            <div className="font-mono text-[11px] text-text-muted">
              {thread.accountId}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                  riskStyle[c.riskLevel],
                )}
              >
                {c.riskLevel} risk
              </span>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                  c.contactableNow ? "bg-success-bg text-success" : "bg-danger-bg text-danger",
                )}
              >
                {c.contactableNow ? (
                  <ShieldCheck className="h-3 w-3" />
                ) : (
                  <ShieldAlert className="h-3 w-3" />
                )}
                {c.contactableNow ? "Contactable now" : "Not contactable"}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-text-secondary">
              Window: {c.contactWindow}
            </div>
          </div>
        </div>
      </div>

      {/* Outstanding */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <div className="text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
          Outstanding
        </div>
        <div className="mt-1 font-mono text-[22px] font-bold text-brand-navy tabular">
          ₹{c.outstanding.toLocaleString("en-IN")}
        </div>
        <div className="text-[12px] text-text-secondary">{c.outstandingAging}</div>
      </div>

      {/* Next EMI + last promise */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-3 shadow-card">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.4px] text-text-muted">
            Next EMI
          </div>
          <div className="mt-1 font-mono text-[15px] font-semibold text-text-primary tabular">
            {c.nextEmiAmount ? `₹${c.nextEmiAmount.toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="text-[11px] text-text-secondary">{c.nextEmiDate}</div>
        </div>
        <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-3 shadow-card">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.4px] text-text-muted">
            Last promise
          </div>
          {c.lastPromise ? (
            <>
              <div className="mt-1 font-mono text-[15px] font-semibold text-text-primary tabular">
                ₹{c.lastPromise.amount.toLocaleString("en-IN")}
              </div>
              <div className="flex items-center gap-1 text-[11px] text-text-secondary">
                <span>{c.lastPromise.date}</span>
                <span
                  className={cn(
                    "ml-auto rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold",
                    promiseStyle[c.lastPromise.status],
                  )}
                >
                  {c.lastPromise.status}
                </span>
              </div>
            </>
          ) : (
            <div className="mt-1 text-[12px] text-text-secondary">None on file</div>
          )}
        </div>
      </div>

      {/* Open disputes */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
            Open disputes
          </span>
          <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
            {c.openDisputes.length}
          </span>
        </div>
        {c.openDisputes.length === 0 ? (
          <div className="text-[12px] text-text-secondary">No open disputes.</div>
        ) : (
          <ul className="space-y-1.5">
            {c.openDisputes.map((d) => (
              <li
                key={d.id}
                className="flex items-start gap-2 rounded-md border border-[var(--border-token)] bg-surface-sunken px-2.5 py-1.5"
              >
                <AlertOctagon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                <div className="min-w-0">
                  <div className="font-mono text-[10.5px] text-text-muted">
                    {d.id}
                  </div>
                  <div className="text-[12px] text-text-primary">{d.summary}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Recent interactions */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
          Recent interactions
        </div>
        <ul className="space-y-2">
          {c.recentInteractions.map((r) => {
            const Icon = r.kind === "call" ? Phone : MessageCircle;
            return (
              <li key={r.id} className="flex items-start gap-2">
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-muted" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] text-text-primary">
                    {r.summary}
                  </div>
                  <div className="text-[11px] text-text-secondary">{r.when}</div>
                </div>
                <span
                  className={cn(
                    "mt-1 h-2 w-2 shrink-0 rounded-full",
                    sentimentColor[r.sentiment],
                  )}
                  title={`${r.sentiment} sentiment`}
                />
              </li>
            );
          })}
        </ul>
      </div>

      {/* Quick actions */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
          Quick actions
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => toast("Opening full Customer 360")}
            className="col-span-2 inline-flex items-center justify-center gap-1.5 rounded-md bg-brand-primary px-3 py-2 text-[12.5px] font-semibold text-white hover:bg-brand-primary-hover active:scale-[0.98]"
          >
            Open full Customer 360
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => toast("Create PTP — coming soon")}
            className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--border-token)] bg-white px-2.5 py-2 text-[12px] font-medium text-text-primary hover:bg-brand-tint hover:text-brand-primary-dark"
          >
            <HandCoins className="h-3.5 w-3.5 text-brand-primary" />
            Create PTP
          </button>
          <button
            type="button"
            onClick={() => toast("Raise dispute — coming soon")}
            className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--border-token)] bg-white px-2.5 py-2 text-[12px] font-medium text-text-primary hover:bg-brand-tint hover:text-brand-primary-dark"
          >
            <AlertOctagon className="h-3.5 w-3.5 text-brand-primary" />
            Raise dispute
          </button>
        </div>
      </div>
    </aside>
  );
}
