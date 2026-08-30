import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { CalendarClock, ChevronRight, Phone, Sparkles } from "lucide-react";
import { useWorkspaceSummary, enactedByLabel, type WorkspaceSlaCountdown } from "@/api/workspace";
import { fetchCallbacks, startCall } from "@/api/callbacks";
import { entityTypeFromSlaLabel, navigateWorkItem } from "@/lib/workspace-nav";
import { SlaPill, formatInMinutes } from "@/components/ui/SlaPill";
import { fmtOfferAmount } from "@/lib/offer-policy";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";

type SlaRow = WorkspaceSlaCountdown & {
  kind: string;
  subject: string;
};

function parseSla(row: WorkspaceSlaCountdown): SlaRow {
  const parts = row.label
    .split("·")
    .map((p) => p.trim())
    .filter(Boolean);
  return {
    ...row,
    kind: parts[0] || "item",
    subject: parts.slice(1).join(" · ") || row.label,
  };
}

const LEVEL_RANK: Record<string, number> = { breach: 3, warn: 2, ok: 1 };

export function NeedsAttention() {
  const navigate = useNavigate();
  const { data } = useWorkspaceSummary("me");
  const nextCallback = data?.nextCallback;
  const nextLead = data?.nextLead;
  const rows = useMemo(() => (data?.slaCountdowns ?? []).map(parseSla), [data?.slaCountdowns]);

  const [startingCall, setStartingCall] = useState(false);

  const onStartCall = async () => {
    if (!nextCallback || startingCall) return;
    setStartingCall(true);
    try {
      const list = await fetchCallbacks();
      const cb = list.find((c) => c.id === nextCallback.id);
      void navigate({ to: "/callbacks", search: { id: nextCallback.id } });
      if (cb) {
        await startCall(cb);
        toast.success(`Starting call with ${nextCallback.customer}`);
      } else {
        toast.message(`Opening callbacks — ${nextCallback.customer} at ${nextCallback.time}`);
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Could not start call");
      void navigate({ to: "/callbacks", search: { id: nextCallback.id } });
    } finally {
      setStartingCall(false);
    }
  };

  const columns = useMemo<RecordsColumn<SlaRow>[]>(
    () => [
      {
        id: "subject",
        header: "Item",
        sticky: true,
        sortable: true,
        sortValue: (row) => row.subject,
        className: "min-w-[16rem]",
        cell: (row) => {
          const entityType = entityTypeFromSlaLabel(row.label);
          return (
            <button
              type="button"
              disabled={!entityType}
              onClick={() => {
                if (!entityType) return;
                navigateWorkItem(navigate, { id: row.id, entityType });
              }}
              className="flex min-w-0 items-center gap-100 text-left disabled:cursor-default"
            >
              <RecordsAvatarMark label={row.subject || "?"} />
              <span className="min-w-0">
                <span className="block truncate text-body font-medium text-text-brand hover:underline">
                  {row.subject || row.label}
                </span>
                <span className="block truncate font-mono text-body-small text-text-subtlest">
                  {row.id}
                </span>
              </span>
            </button>
          );
        },
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">open</span>
          </span>
        ),
      },
      {
        id: "kind",
        header: "Type",
        sortable: true,
        sortValue: (row) => row.kind,
        className: "min-w-[8rem] capitalize whitespace-nowrap",
        cell: (row) => (
          <span className="inline-flex items-center gap-075">
            <span className="text-body capitalize text-text">{row.kind}</span>
            {enactedByLabel(row.enactedBy) ? (
              <span className="rounded-medium bg-surface-sunken px-075 py-025 text-body-small text-text-subtlest">
                {enactedByLabel(row.enactedBy)}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        id: "sla",
        header: "SLA",
        sortable: true,
        sortValue: (row) => LEVEL_RANK[row.level] ?? 0,
        className: "min-w-[10rem] whitespace-nowrap",
        cell: (row) => <SlaPill level={row.level} label={row.remaining} />,
        footer: (visible) => {
          const breach = visible.filter((r) => r.level === "breach").length;
          return <span className="text-body-small text-text-subtlest">{breach} overdue</span>;
        },
      },
      {
        id: "open",
        header: "Open",
        align: "right",
        className: "min-w-[5.5rem] whitespace-nowrap",
        cell: (row) => {
          const entityType = entityTypeFromSlaLabel(row.label);
          return (
            <button
              type="button"
              disabled={!entityType}
              onClick={() => {
                if (!entityType) return;
                navigateWorkItem(navigate, { id: row.id, entityType });
              }}
              className="inline-flex items-center gap-050 rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-150 py-050 text-body-small font-medium text-text-brand transition-colors hover:border-border-brand/40 hover:bg-background-brand-subtlest-hovered disabled:cursor-default disabled:opacity-50"
            >
              Open
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          );
        },
      },
    ],
    [navigate],
  );

  return (
    <div className="flex flex-col gap-200">
      <div className="rounded-xlarge border border-border bg-surface px-250 py-200">
        <div className="flex flex-wrap items-center justify-between gap-150">
          <div className="min-w-0">
            <h3 className="heading-xsmall text-text">Next scheduled callback</h3>
            {nextCallback ? (
              <p className="mt-050 truncate text-body text-text-subtle">
                <span className="font-medium text-text">{nextCallback.customer}</span>
                <span className="text-text-subtlest"> · {nextCallback.accountId}</span>
                <span> · {nextCallback.reason}</span>
              </p>
            ) : (
              <p className="mt-050 text-body text-text-subtlest">
                No upcoming callbacks on your queue.
              </p>
            )}
          </div>
          {nextCallback && (
            <div className="flex flex-wrap items-center gap-100">
              <span className="inline-flex items-center gap-050 rounded-medium bg-surface-sunken px-100 py-050 text-body-small font-medium text-text">
                <CalendarClock className="h-3.5 w-3.5 text-text-brand" />
                {nextCallback.time} {nextCallback.timezone}
              </span>
              <span className="inline-flex shrink-0 items-center rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-100 py-025 text-body-small font-medium text-text-brand">
                {formatInMinutes(nextCallback.inMinutes)}
              </span>
              <button
                type="button"
                onClick={() => void onStartCall()}
                disabled={startingCall}
                className="inline-flex items-center gap-075 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-hovered disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Phone className="h-3.5 w-3.5" />
                {startingCall ? "Starting…" : "Start call"}
              </button>
              <button
                type="button"
                onClick={() => void navigate({ to: "/callbacks", search: { id: nextCallback.id } })}
                className="rounded-medium border border-border bg-surface px-150 py-075 text-body-small font-medium text-text hover:bg-surface-sunken"
              >
                Reschedule
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xlarge border border-border bg-surface px-250 py-200">
        <div className="flex flex-wrap items-center justify-between gap-150">
          <div className="min-w-0">
            <h3 className="heading-xsmall text-text">Next lead</h3>
            {nextLead ? (
              <p className="mt-050 truncate text-body text-text-subtle">
                <span className="font-medium text-text">{nextLead.customer}</span>
                <span className="text-text-subtlest"> · {nextLead.accountId}</span>
                <span>
                  {" "}
                  · {nextLead.productName}
                  {nextLead.amount != null ? ` · ${fmtOfferAmount(nextLead.amount)}` : ""}
                </span>
              </p>
            ) : (
              <p className="mt-050 text-body text-text-subtlest">No open leads on your queue.</p>
            )}
            {nextLead?.reason ? (
              <p className="mt-025 truncate text-body-small text-text-subtlest">
                {nextLead.reason}
              </p>
            ) : null}
          </div>
          {nextLead && (
            <div className="flex flex-wrap items-center gap-100">
              {nextLead.window ? (
                <span className="inline-flex items-center gap-050 rounded-medium bg-surface-sunken px-100 py-050 text-body-small font-medium text-text">
                  <CalendarClock className="h-3.5 w-3.5 text-text-brand" />
                  {nextLead.window}
                </span>
              ) : null}
              <span className="inline-flex shrink-0 items-center rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-100 py-025 text-body-small font-medium capitalize text-text-brand">
                {nextLead.stage.replace(/_/g, " ")}
              </span>
              <button
                type="button"
                onClick={() => void navigate({ to: "/upsell", search: { id: nextLead.id } })}
                className="inline-flex items-center gap-075 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-hovered"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Open lead
              </button>
            </div>
          )}
        </div>
      </div>

      <section className="overflow-hidden rounded-xlarge border border-border bg-surface">
        <div className="flex items-center justify-between gap-150 border-b border-border px-250 py-200">
          <div>
            <h2 className="heading-xsmall text-text">Needs attention</h2>
            <p className="mt-025 text-body-small text-text-subtle">
              Personal SLA timers on work assigned to you
            </p>
          </div>
        </div>
        <div className="bg-surface-sunken/25 p-100">
          <RecordsTable
            rows={rows}
            getRowId={(row) => row.id}
            columns={columns}
            emptyMessage="No open SLA timers."
            ariaLabel="Personal SLA countdowns"
            defaultSort={{ id: "sla", dir: -1 }}
            className="border-0 shadow-none"
            tableClassName="min-w-[48rem]"
          />
        </div>
      </section>
    </div>
  );
}
