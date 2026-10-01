import type { ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { CalendarClock, ChevronRight, Phone, Sparkles } from "lucide-react";
import {
  dueLabel,
  enactedByLabel,
  useWorkspaceSummary,
  type DueFilter,
  type WorkItem,
  type WorkspaceScope,
} from "@/api/workspace";
import { useStartCallback } from "@/api/callbacks";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { SlaPill } from "@/components/ui/SlaPill";
import { fmtDateTime } from "@/lib/format";
import { fmtOfferAmount } from "@/lib/offer-policy";
import { useNow } from "@/lib/use-now";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xlarge border border-border bg-surface px-250 py-200">
      <h3 className="heading-xsmall text-text">{title}</h3>
      {children}
    </div>
  );
}

function Unavailable({ what, retry }: { what: string; retry: () => void }) {
  return (
    <p className="mt-050 text-body text-text-danger">
      Couldn’t load {what}.{" "}
      <button type="button" onClick={retry} className="font-medium underline">
        Retry
      </button>
    </p>
  );
}

const btnPrimary =
  "inline-flex items-center gap-075 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-hovered disabled:cursor-not-allowed disabled:opacity-60";
const btnSecondary =
  "rounded-medium border border-border bg-surface px-150 py-075 text-body-small font-medium text-text hover:bg-surface-sunken";

/** What needs the operator next: the next appointment, the next lead, and the
 *  overdue or nearly-due work, with totals and a way to see all of it. */
export function NeedsAttention({
  scope,
  onViewAll,
}: {
  scope: WorkspaceScope;
  onViewAll: (due: DueFilter) => void;
}) {
  const navigate = useNavigate();
  const now = useNow();
  const { data, isPending, isError, refetch } = useWorkspaceSummary(scope);
  const startCallback = useStartCallback();
  const failed = isError && !data;
  const nextCallback = data?.nextCallback;
  const nextLead = data?.nextLead;
  const rows = data?.attention ?? [];
  const counts = data?.queueCounts;
  const attentionTotal = counts ? counts.overdue + counts.dueSoon : 0;
  const scopeName = scope === "me" ? "your queue" : "the team pool";

  const openCallback = (id: string) => void navigate({ to: "/callbacks", search: { id } });

  return (
    <div className="flex flex-col gap-200">
      <div className="grid gap-200 lg:grid-cols-2">
        <Card title="Next callback">
          {failed ? (
            <Unavailable what="callbacks" retry={() => void refetch()} />
          ) : isPending ? (
            <p className="mt-050 text-body text-text-subtlest">Loading…</p>
          ) : nextCallback ? (
            <>
              <p className="mt-050 truncate text-body text-text-subtle">
                <span className="font-medium text-text">{nextCallback.customer}</span>
                <span className="text-text-subtlest"> · {nextCallback.accountId || "—"}</span>
                <span> · {nextCallback.reason}</span>
              </p>
              <div className="mt-150 flex flex-wrap items-center gap-100">
                <span className="inline-flex items-center gap-050 rounded-medium bg-surface-sunken px-100 py-050 text-body-small font-medium text-text">
                  <CalendarClock className="h-3.5 w-3.5 text-text-brand" />
                  {nextCallback.time} {nextCallback.timezone} ·{" "}
                  {dueLabel(nextCallback.scheduledAt, now)}
                </span>
                {nextCallback.status !== "scheduled" && (
                  <span className="text-body-small capitalize text-text-subtlest">
                    {nextCallback.status}
                  </span>
                )}
                <button
                  type="button"
                  disabled={startCallback.isPending}
                  onClick={() =>
                    startCallback.mutate(
                      { id: nextCallback.id },
                      { onSettled: () => openCallback(nextCallback.id) },
                    )
                  }
                  className={btnPrimary}
                >
                  <Phone className="h-3.5 w-3.5" />
                  {startCallback.isPending ? "Updating…" : "Begin callback"}
                </button>
                <button
                  type="button"
                  onClick={() => openCallback(nextCallback.id)}
                  className={btnSecondary}
                >
                  Open callback
                </button>
              </div>
            </>
          ) : (
            <p className="mt-050 text-body text-text-subtlest">
              No upcoming callbacks in {scopeName}.
            </p>
          )}
        </Card>

        <Card title="Next lead">
          {failed ? (
            <Unavailable what="leads" retry={() => void refetch()} />
          ) : isPending ? (
            <p className="mt-050 text-body text-text-subtlest">Loading…</p>
          ) : nextLead ? (
            <>
              <p className="mt-050 truncate text-body text-text-subtle">
                <span className="font-medium text-text">{nextLead.customer}</span>
                <span className="text-text-subtlest"> · {nextLead.accountId || "—"}</span>
                <span>
                  {" "}
                  · {nextLead.productName}
                  {nextLead.amount != null ? ` · ${fmtOfferAmount(nextLead.amount)}` : ""}
                </span>
              </p>
              <p className="mt-025 text-body-small text-text-subtlest">
                Highest-priority open lead ({nextLead.priority}), then highest value
                {nextLead.nextFollowupAt
                  ? ` · next follow-up ${fmtDateTime(nextLead.nextFollowupAt)}`
                  : " · no follow-up planned"}
              </p>
              <div className="mt-150 flex flex-wrap items-center gap-100">
                <span className="inline-flex items-center rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-100 py-025 text-body-small font-medium capitalize text-text-brand">
                  {nextLead.stage.replace(/_/g, " ")}
                </span>
                {nextLead.window ? (
                  <span className="text-body-small text-text-subtlest">
                    Prefers {nextLead.window}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => void navigate({ to: "/upsell", search: { id: nextLead.id } })}
                  className={btnPrimary}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  Open lead
                </button>
              </div>
            </>
          ) : (
            <p className="mt-050 text-body text-text-subtlest">No open leads in {scopeName}.</p>
          )}
        </Card>
      </div>

      <section className="rounded-xlarge border border-border bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-150 border-b border-border px-250 py-200">
          <div>
            <h2 className="heading-xsmall text-text">Needs attention</h2>
            <p className="mt-025 text-body-small text-text-subtle">
              {counts
                ? `${counts.overdue} overdue · ${counts.dueSoon} due within 2 hours in ${scopeName}`
                : "Overdue work and work due within 2 hours"}
            </p>
          </div>
          {counts && attentionTotal > rows.length && (
            <button
              type="button"
              onClick={() => onViewAll(counts.overdue ? "overdue" : "due_soon")}
              className="inline-flex items-center gap-050 text-body-small font-medium text-text-brand hover:underline"
            >
              Showing {rows.length} of {attentionTotal} · View all
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {failed ? (
          <div className="px-250 py-200">
            <Unavailable what="deadlines" retry={() => void refetch()} />
          </div>
        ) : isPending ? (
          <p className="px-250 py-200 text-body text-text-subtlest">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="px-250 py-200 text-body text-text-subtlest">
            Nothing overdue or due within 2 hours.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((row) => (
              <AttentionRow key={`${row.entityType}:${row.id}`} row={row} now={now} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function AttentionRow({ row, now }: { row: WorkItem; now: number }) {
  const navigate = useNavigate();
  const by = enactedByLabel(row.enactedBy);
  return (
    <li className="flex items-center gap-150 px-250 py-100">
      <SlaPill level={row.sla} label={row.dueAt ? dueLabel(row.dueAt, now) : row.slaLabel} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-body text-text">
          <span className="font-medium">{row.type}</span>
          <span className="text-text-subtle"> · {row.customer}</span>
          {by ? <span className="text-body-small text-text-subtlest"> · {by}</span> : null}
        </div>
        <div className="truncate text-body-small text-text-subtlest" title={row.detail}>
          {row.detail}
        </div>
      </div>
      <button
        type="button"
        onClick={() => navigateWorkItem(navigate, row)}
        aria-label={`Open ${row.type} for ${row.customer}`}
        className="inline-flex shrink-0 items-center gap-050 rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-150 py-050 text-body-small font-medium text-text-brand hover:bg-background-brand-subtlest-hovered"
      >
        Open
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}
