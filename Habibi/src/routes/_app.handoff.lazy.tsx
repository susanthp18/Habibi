import { useState } from "react";
import { createLazyFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CaseHeader } from "@/components/handoff/CaseHeader";
import { SentimentMeter } from "@/components/handoff/SentimentMeter";
import { Transcript } from "@/components/handoff/Transcript";
import { AISuggestedResponses } from "@/components/handoff/AISuggestedResponses";
import { HandoffCopilot } from "@/components/handoff/HandoffCopilot";
import { CustomerContextPanel } from "@/components/handoff/CustomerContextPanel";
import { ComplianceChecklist } from "@/components/handoff/ComplianceChecklist";
import { WrapUpBar } from "@/components/handoff/WrapUpBar";
import { HandoffAlerts, HandoffQueueList } from "@/components/handoff/HandoffQueue";
import { handoffErrorWords } from "@/components/handoff/handoff-words";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { postSupervisorAction } from "@/api/floor";
import { useCannedResponses } from "@/api/inbox";
import { can, useMe } from "@/api/me";
import {
  useAcceptSuggestion,
  useClaimHandoff,
  useHandoffQueue,
  useHandoffSession,
  useRecordDisclosure,
  useWrapUpHandoff,
  type ComplianceItem,
  type HandoffSession,
  type WrapUpPayload,
} from "@/api/handoff";
import { useMinWidth } from "@/hooks/use-min-width";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/_app/handoff")({
  component: HandoffPage,
});

type RailTab = "context" | "suggest" | "compliance";
type ClaimError = { interactionId: string; message: string };

function HandoffPage() {
  const { interactionId, customerId, mode } = Route.useSearch();
  const navigate = useNavigate({ from: "/handoff" });
  const claimMut = useClaimHandoff();
  const [claimError, setClaimError] = useState<ClaimError | null>(null);

  const claim = (id: string) => {
    setClaimError(null);
    claimMut.mutate(id, {
      onSuccess: (session) => {
        void navigate({ search: { interactionId: session.interactionId, customerId } });
      },
      onError: (e) => setClaimError({ interactionId: id, message: handoffErrorWords(e) }),
    });
  };

  if (interactionId) {
    return (
      <CasePage
        // A new case starts clean: nothing typed or ticked for one leaks into the next.
        key={interactionId}
        interactionId={interactionId}
        monitor={mode === "monitor"}
        onClaim={claim}
        claiming={claimMut.isPending}
        claimError={claimError?.interactionId === interactionId ? claimError.message : null}
      />
    );
  }
  return (
    <QueuePage
      customerId={customerId}
      onClaim={claim}
      claimingId={claimMut.isPending ? claimMut.variables : null}
      claimError={claimError}
    />
  );
}

function QueuePage({
  customerId,
  onClaim,
  claimingId,
  claimError,
}: {
  customerId?: string;
  onClaim: (id: string) => void;
  claimingId: string | null | undefined;
  claimError: ClaimError | null;
}) {
  const queue = useHandoffQueue(customerId);
  if (queue.isError && !queue.data) {
    return (
      <div className="grid h-full place-items-center p-400">
        <QueryErrorBanner label="the handoff queue" error={queue.error} />
      </div>
    );
  }
  if (!queue.data) return <HandoffSkeleton />;
  const mine = queue.data.activeInteractionId;
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      {queue.isRefetchError ? <StaleBanner at={queue.dataUpdatedAt} what="the queue" /> : null}
      {mine ? (
        <div className="mx-auto mt-200 flex w-full max-w-2xl items-center justify-between gap-150 rounded-large border border-border-brand bg-background-brand-subtlest px-150 py-100">
          <span className="text-body-small text-text">You have a case open.</span>
          <Link
            to="/handoff"
            search={{ interactionId: mine, customerId }}
            className="text-body-small font-semibold text-text-brand hover:underline"
          >
            Resume it
          </Link>
        </div>
      ) : null}
      <HandoffQueueList
        items={queue.data.items}
        total={queue.data.total}
        claimingId={claimingId}
        claimError={claimError}
        onClaim={onClaim}
      />
    </div>
  );
}

function CasePage({
  interactionId,
  monitor: monitorMode,
  onClaim,
  claiming,
  claimError,
}: {
  interactionId: string;
  monitor: boolean;
  onClaim: (id: string) => void;
  claiming: boolean;
  claimError: string | null;
}) {
  const q = useHandoffSession(interactionId);
  if (!q.data) {
    if (q.isError) {
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-150 bg-surface p-300">
          <QueryErrorBanner label="the case" error={q.error} />
          <Link to="/handoff" search={{}} className="text-body-small font-semibold text-text-brand">
            Back to queue
          </Link>
        </div>
      );
    }
    return <HandoffSkeleton />;
  }
  return (
    <HandoffCase
      session={q.data}
      monitor={monitorMode || q.data.monitor}
      stale={q.isRefetchError ? q.dataUpdatedAt : null}
      onClaim={() => onClaim(interactionId)}
      claiming={claiming}
      claimError={claimError}
    />
  );
}

function HandoffCase({
  session,
  monitor,
  stale,
  onClaim,
  claiming,
  claimError,
}: {
  session: HandoffSession;
  monitor: boolean;
  /** When the last good snapshot was read, if the latest refresh failed. */
  stale: number | null;
  onClaim: () => void;
  claiming: boolean;
  claimError: string | null;
}) {
  const { activeCall, customerContext, transcriptScript, suggestions, complianceItems, alerts } =
    session;
  const { data: me } = useMe();
  const canSupervise = can(me, "perm-supervisor-write");
  const canClaim = can(me, "perm-interactions-write");
  const open = session.status !== "completed";
  const pending = session.status === "pending_claim";
  const mine = session.claimed && !monitor;
  const readOnly = !mine || !open;

  const qc = useQueryClient();
  const navigate = useNavigate({ from: "/handoff" });
  const canned = useCannedResponses();
  const wrapMut = useWrapUpHandoff();
  const disclose = useRecordDisclosure(session.interactionId);
  const accept = useAcceptSuggestion(session.interactionId);
  const wide = useMinWidth(1024);
  const [wrapOpen, setWrapOpen] = useState(false);
  const [wrapError, setWrapError] = useState<string | null>(null);
  const [railTab, setRailTab] = useState<RailTab>("context");

  const saveWrap = (payload: WrapUpPayload) => {
    setWrapError(null);
    wrapMut.mutate(
      { interactionId: session.interactionId, customerId: session.customerId, ...payload },
      {
        onSuccess: () => {
          toast.success("Wrap-up saved");
          void navigate({ search: {} });
        },
        onError: (e) => setWrapError(handoffErrorWords(e)),
      },
    );
  };

  const toggleDisclosure = (item: ComplianceItem, read: boolean) => {
    disclose.mutate(
      { itemId: item.id, ruleId: item.ruleId, label: item.label, read },
      { onError: (e) => toast.error(handoffErrorWords(e)) },
    );
  };

  const takeOver = () => {
    // The Floor's takeover: the open handoff becomes the supervisor's case.
    void postSupervisorAction(session.interactionId, "barge")
      .then(() => {
        toast.success("Case taken over");
        void qc.invalidateQueries({ queryKey: ["handoff"] });
        void navigate({
          search: { interactionId: session.interactionId, customerId: session.customerId },
          replace: true,
        });
      })
      .catch((e) => toast.error(handoffErrorWords(e)));
  };

  const copilot = <HandoffCopilot interactionId={session.interactionId} canSignal={canSupervise} />;
  const context = (
    <>
      <HandoffAlerts items={alerts} canAck={canSupervise} />
      <CustomerContextPanel call={activeCall} context={customerContext} readOnly={readOnly} />
    </>
  );
  const suggest = (
    <>
      {copilot}
      <AISuggestedResponses
        items={suggestions}
        onUsed={
          readOnly
            ? undefined
            : (id) => accept.mutate(id, { onError: (e) => toast.error(handoffErrorWords(e)) })
        }
        canned={canned.data}
        cannedFailed={canned.isError}
      />
    </>
  );
  const compliance = (
    <ComplianceChecklist
      items={complianceItems}
      onToggle={toggleDisclosure}
      pendingId={disclose.isPending ? disclose.variables?.itemId : null}
      readOnly={readOnly}
    />
  );

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface">
      <CaseHeader
        call={activeCall}
        monitor={monitor}
        onWrapUp={mine && open && !wrapOpen ? () => setWrapOpen(true) : undefined}
      />
      {stale ? <StaleBanner at={stale} what="this case" /> : null}
      {pending && !monitor ? (
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-150 border-b border-border bg-background-warning-subtler px-250 py-100">
          <p className="text-body-small text-text">
            This case is waiting for an agent. Claim it to work it and wrap it up.
          </p>
          <div className="flex items-center gap-150">
            {claimError ? (
              <p role="alert" className="text-body-small text-text-danger">
                {claimError}
              </p>
            ) : null}
            {canClaim ? (
              <button
                type="button"
                disabled={claiming}
                onClick={onClaim}
                className="rounded-medium bg-background-brand-bold px-200 py-075 text-body-small font-semibold text-text-inverse hover:bg-background-brand-bold-hovered disabled:opacity-60"
              >
                {claiming ? "Claiming…" : "Claim this case"}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {monitor ? (
        <div className="flex shrink-0 items-center justify-between gap-150 border-b border-border bg-background-brand-subtlest/50 px-250 py-075">
          <p className="text-body-small text-text-brand">
            {session.claimed
              ? `Watching ${activeCall.agentName}'s case — read-only.`
              : "Watching an unclaimed case — read-only."}
          </p>
          {canSupervise && open ? (
            <button
              type="button"
              onClick={session.claimed ? takeOver : onClaim}
              className="rounded-medium bg-background-danger-bold px-150 py-050 text-body-small font-semibold text-text-inverse hover:bg-background-danger-bold-hovered"
            >
              {session.claimed ? "Take over case" : "Claim this case"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <SentimentMeter series={session.sentimentSeries} />
          <Transcript
            turns={transcriptScript}
            speakers={session.speakers}
            callLive={activeCall.callState === "live"}
          />
        </div>
        {wide ? (
          <aside className="flex w-[22.5rem] shrink-0 flex-col gap-150 overflow-y-auto border-l border-border bg-surface px-150 py-150 xl:w-[25rem]">
            {context}
            {suggest}
            {compliance}
          </aside>
        ) : null}
      </div>

      {!wide ? (
        <div className="flex min-h-0 flex-col border-t border-border">
          <div
            role="tablist"
            aria-label="Case details"
            className="flex shrink-0 gap-050 border-b border-border px-150 py-075"
          >
            {(
              [
                ["context", "Context"],
                ["suggest", "Suggest"],
                ["compliance", "Compliance"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={railTab === key}
                aria-controls={`handoff-tab-${key}`}
                onClick={() => setRailTab(key)}
                className={cn(
                  "rounded-medium px-100 py-050 text-body-small font-semibold",
                  railTab === key
                    ? "bg-background-brand-subtlest text-text-brand"
                    : "text-text-subtle",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            id={`handoff-tab-${railTab}`}
            role="tabpanel"
            className="max-h-[40vh] space-y-150 overflow-y-auto px-150 py-150"
          >
            {railTab === "context" && context}
            {railTab === "suggest" && suggest}
            {railTab === "compliance" && compliance}
          </div>
        </div>
      ) : null}

      {mine && open ? (
        <WrapUpBar
          open={wrapOpen}
          outcomes={session.outcomes}
          saving={wrapMut.isPending}
          error={wrapError}
          defaultPtpAmount={customerContext.nextEmi?.amount}
          actorId={me?.id}
          onClose={() => setWrapOpen(false)}
          onSave={saveWrap}
        />
      ) : null}
    </div>
  );
}

function StaleBanner({ at, what }: { at: number; what: string }) {
  const time = new Date(at).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <p
      role="status"
      className="shrink-0 border-b border-border bg-background-warning-subtler px-250 py-075 text-body-small text-text"
    >
      Couldn't refresh {what} — showing it as of {time}.
    </p>
  );
}

function HandoffSkeleton() {
  return (
    <div
      className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface"
      aria-busy="true"
    >
      <Skeleton className="h-800 w-full rounded-none" />
      <div className="flex min-h-0 flex-1 gap-150 p-150">
        <div className="flex min-w-0 flex-1 flex-col gap-150">
          <Skeleton className="h-24 w-full rounded-large" />
          <Skeleton className="min-h-0 flex-1 rounded-large" />
        </div>
        <div className="hidden w-[22.5rem] shrink-0 flex-col gap-150 lg:flex xl:w-[25rem]">
          <Skeleton className="h-48 rounded-large" />
          <Skeleton className="h-40 rounded-large" />
          <Skeleton className="h-40 rounded-large" />
        </div>
      </div>
    </div>
  );
}
