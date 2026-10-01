import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw, ShieldAlert } from "lucide-react";
import { AvailabilityToggle } from "@/components/workspace/AvailabilityToggle";
import { StatsStrip } from "@/components/workspace/StatsStrip";
import { AssignedQueue, type QueueTab } from "@/components/workspace/AssignedQueue";
import { NeedsAttention } from "@/components/workspace/NeedsAttention";
import { useMe } from "@/api/me";
import { useWorkspaceSummary, type DueFilter, type WorkspaceScope } from "@/api/workspace";
import { BRAND } from "@/lib/brand";
import { entraDisplayName } from "@/lib/sso";
import { fmtRelative } from "@/lib/format";
import { useNow } from "@/lib/use-now";

export const Route = createFileRoute("/_app/")({
  head: () => ({
    meta: [
      { title: `My Workspace — ${BRAND.titleSuffix}` },
      {
        name: "description",
        content:
          "The operator's home: what needs you next, your queue and the team pool, and your own calls this week.",
      },
    ],
  }),
  component: WorkspacePage,
});

const IST = "Asia/Kolkata";

/** Greeting and date in IST, the zone every time on this page is shown in. */
function istGreeting(now: number) {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { timeZone: IST, hour: "2-digit", hour12: false }).format(now),
  );
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const date = new Date(now).toLocaleDateString("en-IN", {
    timeZone: IST,
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  return { greeting, date };
}

function firstName(full: string | undefined | null): string {
  return full?.trim().split(/\s+/)[0] ?? "";
}

function WorkspacePage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const now = useNow();
  const { data: me } = useMe();
  const [scope, setScope] = useState<WorkspaceScope>("me");
  const [tab, setTab] = useState<QueueTab>("all");
  const [due, setDue] = useState<DueFilter | undefined>();
  const summary = useWorkspaceSummary(scope);
  const mine = useWorkspaceSummary("me");
  const blocked = summary.data?.callbacksBlockedCount ?? 0;
  const blockedPartial = summary.data?.callbacksBlockedPartial ?? false;
  // A refresh that failed over cached data: the cards still show the last good
  // read, so say when that was instead of passing it off as current.
  const stale = [summary, mine].find((q) => q.isError && q.data);
  const name = firstName(me?.name) || firstName(entraDisplayName());
  const { greeting, date } = istGreeting(now);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["work-items"] });
    void qc.invalidateQueries({ queryKey: ["workspace-summary"] });
    void qc.invalidateQueries({ queryKey: ["me-presence"] });
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <div className="mx-auto w-full max-w-[90rem] px-300 py-300">
        <div className="flex flex-wrap items-start justify-between gap-200">
          <div>
            <h1 className="heading-medium text-text">My workspace</h1>
            <p className="mt-075 text-body text-text-subtle">
              {name ? `${greeting}, ${name}` : greeting} · {date}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-150">
            <button
              type="button"
              onClick={refresh}
              className="inline-flex items-center gap-075 text-body-small text-text-subtlest hover:text-text"
              title="Refresh now"
            >
              <RefreshCw
                className={summary.isFetching ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"}
              />
              {summary.dataUpdatedAt
                ? `Updated ${fmtRelative(new Date(summary.dataUpdatedAt).toISOString())}`
                : "Refresh"}
            </button>
            <AvailabilityToggle />
          </div>
        </div>

        {stale && (
          <div
            role="status"
            className="mt-250 flex items-center gap-150 rounded-xlarge border border-border-warning/25 bg-background-warning px-200 py-100 text-body-small text-text-warning"
          >
            Couldn’t refresh the workspace — showing data from{" "}
            {new Date(stale.dataUpdatedAt).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })}
            .
            <button type="button" onClick={refresh} className="font-semibold underline">
              Retry
            </button>
          </div>
        )}

        {blocked > 0 && (
          <div className="mt-250 flex items-start gap-150 rounded-xlarge border border-border-warning/25 bg-background-warning px-200 py-150">
            <ShieldAlert className="mt-025 h-4 w-4 shrink-0 text-text-warning" />
            <div className="min-w-0 text-body">
              <span className="font-semibold text-text-warning">
                {blockedPartial ? "At least " : ""}
                {blocked} upcoming callback{blocked === 1 ? " is" : "s are"} booked for a time the
                contact rules would refuse.
              </span>{" "}
              <span className="text-text-subtle">
                An opt-out, DND, the calling hours, the borrower’s window or days, or a hold blocks
                the slot — reschedule before it comes up.
                {blockedPartial ? " Only the soonest 200 upcoming callbacks were checked." : ""}
              </span>
            </div>
            <button
              type="button"
              onClick={() => void navigate({ to: "/callbacks" })}
              className="ml-auto shrink-0 rounded-medium border border-border-warning/30 bg-surface px-150 py-075 text-body-small font-semibold text-text-warning hover:bg-background-warning"
            >
              Open callbacks
            </button>
          </div>
        )}

        <div className="mt-300">
          <StatsStrip />
        </div>

        <div className="mt-300 space-y-200">
          <NeedsAttention
            scope={scope}
            onViewAll={(next) => {
              setTab("all");
              setDue(next);
              document.getElementById("workspace-queue")?.scrollIntoView({ behavior: "smooth" });
            }}
          />
          <div id="workspace-queue">
            <AssignedQueue
              scope={scope}
              onScope={setScope}
              tab={tab}
              onTab={setTab}
              due={due}
              onDue={setDue}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
