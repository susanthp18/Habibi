import { Headphones, Search, ShieldAlert } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Lozenge } from "@/components/ui/lozenge";
import type { HandoffAlert, HandoffQueueItem } from "@/api/handoff";
import { useAckFloorAlert } from "@/api/floor";
import { cn } from "@/lib/utils";
import { TransferLozenge } from "./CaseHeader";
import { waitWords } from "./handoff-words";

/** A supervisor acknowledges (perm-supervisor-write); everyone else reads. */
export function HandoffAlerts({ items, canAck }: { items: HandoffAlert[]; canAck: boolean }) {
  // The floor's own hook: the alert list is read under both keys, and the
  // component-local copy had no error path at all.
  const ack = useAckFloorAlert([["handoff"]]);

  if (!items.length) return null;

  return (
    <div className="rounded-large border border-border-warning bg-background-warning/40">
      <div className="flex items-center gap-075 border-b border-border px-150 py-100 text-body-small font-semibold text-text">
        <ShieldAlert className="h-3.5 w-3.5 text-text-warning" />
        Alerts on this call
      </div>
      <ul className="divide-y divide-border">
        {items.map((a) => (
          <li key={a.id} className="flex items-start justify-between gap-100 px-150 py-100">
            <div className="min-w-0">
              <div className="text-body-small font-semibold text-text">
                {a.kind.replace(/_/g, " ")}
              </div>
              {a.reason ? <div className="text-body-small text-text-subtle">{a.reason}</div> : null}
            </div>
            {canAck ? (
              <button
                type="button"
                disabled={ack.isPending}
                onClick={() => ack.mutate(a.id)}
                className="shrink-0 text-body-small font-semibold text-text-brand hover:underline disabled:opacity-50"
              >
                Ack
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** How long a caller may wait before the row warns, then alarms (seconds). */
const WAIT_WARN_S = 120;
const WAIT_ALARM_S = 600;

function waitTone(sec: number) {
  return sec >= WAIT_ALARM_S
    ? "font-semibold text-text-danger"
    : sec >= WAIT_WARN_S
      ? "text-text-warning"
      : "text-text-subtlest";
}

function CaseSummary({ item }: { item: HandoffQueueItem }) {
  return (
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-100">
        <span className="truncate font-semibold text-text">{item.customerName}</span>
        <RiskLozenge risk={item.risk} />
        <TransferLozenge outcome={item.transferOutcome} />
      </div>
      <div className="mt-025 text-body-small text-text-subtle">
        {[item.accountId, item.reason.replace(/_/g, " "), item.queue].filter(Boolean).join(" · ")}
      </div>
      <div className={cn("mt-025 tabular text-body-small", waitTone(item.waitSec))}>
        waiting {waitWords(item.waitSec)}
      </div>
    </div>
  );
}

/** The actor's caseload: every open case they hold, to resume. */
export function HandoffCaseload({
  items,
  customerId,
}: {
  items: HandoffQueueItem[];
  customerId?: string;
}) {
  if (!items.length) return null;
  return (
    <section className="space-y-100" aria-labelledby="handoff-mine-heading">
      <h2 id="handoff-mine-heading" className="text-body font-semibold text-text">
        Your open cases ({items.length})
      </h2>
      <ul className="space-y-100">
        {items.map((item) => (
          <li
            key={item.interactionId}
            className="flex items-center gap-150 rounded-large border border-border-brand bg-background-brand-subtlest/40 p-150"
          >
            <CaseSummary item={item} />
            <Link
              to="/handoff"
              search={{ interactionId: item.interactionId, customerId }}
              aria-label={`Resume ${item.customerName}`}
              className="shrink-0 rounded-medium border border-border px-150 py-075 text-body-small font-semibold text-text-brand hover:bg-surface-sunken"
            >
              Resume
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HandoffQueueList({
  items,
  total,
  search,
  onSearch,
  onShowMore,
  canClaim,
  claimingId,
  claimError,
  onClaim,
}: {
  items: HandoffQueueItem[];
  total: number;
  search: string;
  onSearch: (value: string) => void;
  /** Offered while more cases wait than are shown. */
  onShowMore?: () => void;
  /** perm-interactions-write: without it the queue is read-only. */
  canClaim: boolean;
  claimingId?: string | null;
  /** The last claim that failed, shown on its row. */
  claimError?: { interactionId: string; message: string } | null;
  onClaim: (interactionId: string) => void;
}) {
  if (!items.length && !search) {
    return (
      <div className="grid place-items-center p-400 text-center">
        <div>
          <Headphones className="mx-auto mb-150 h-8 w-8 text-text-subtlest" />
          <h1 className="text-sm font-semibold text-text">No handoffs waiting</h1>
          <p className="mt-050 max-w-sm text-body text-text-subtlest">
            When a Voice Studio agent hands a caller to a person, the case lands here for your team
            to claim and follow up.
          </p>
        </div>
      </div>
    );
  }

  return (
    <section className="space-y-150" aria-labelledby="handoff-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-100">
        <h1 id="handoff-heading" className="text-body font-semibold text-text">
          Handoffs waiting
        </h1>
        <span className="text-body-small text-text-subtlest">
          {total > items.length ? `Oldest ${items.length} of ${total}` : `${total} waiting`}
        </span>
      </div>
      <label className="flex items-center gap-075 rounded-medium border border-border bg-surface px-100">
        <Search className="h-3.5 w-3.5 text-text-subtlest" />
        <span className="sr-only">Search waiting cases</span>
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Customer name, customer id or account"
          className="h-400 min-w-0 flex-1 bg-transparent text-body-small text-text outline-none"
        />
      </label>
      {!items.length ? (
        <p className="text-body-small text-text-subtlest">No waiting case matches “{search}”.</p>
      ) : null}
      <ul className="space-y-150">
        {items.map((item) => {
          const failed = claimError?.interactionId === item.interactionId ? claimError : null;
          return (
            <li
              key={item.interactionId}
              className="rounded-large border border-border bg-surface p-150"
            >
              <div className="flex items-center gap-150">
                <CaseSummary item={item} />
                {canClaim ? (
                  <button
                    type="button"
                    disabled={claimingId === item.interactionId}
                    onClick={() => onClaim(item.interactionId)}
                    aria-label={`Claim ${item.customerName}`}
                    className="shrink-0 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-semibold text-text-inverse hover:bg-background-brand-bold-hovered disabled:opacity-60"
                  >
                    {claimingId === item.interactionId ? "Claiming…" : "Claim"}
                  </button>
                ) : null}
              </div>
              {failed ? (
                <p role="alert" className="mt-075 text-body-small text-text-danger">
                  {failed.message}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {onShowMore && total > items.length ? (
        <button
          type="button"
          onClick={onShowMore}
          className="w-full rounded-medium border border-border py-075 text-body-small font-semibold text-text-brand hover:bg-surface-sunken"
        >
          Show {Math.min(50, total - items.length)} more
        </button>
      ) : null}
    </section>
  );
}

export function RiskLozenge({ risk }: { risk: string }) {
  const r = risk.toLowerCase();
  const tone = r === "critical" || r === "high" ? "danger" : r === "medium" ? "warning" : "success";
  return <Lozenge tone={tone}>{risk} risk</Lozenge>;
}
