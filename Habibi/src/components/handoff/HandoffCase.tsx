import { useEffect, useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { CaseHeader } from "./CaseHeader";
import { SentimentMeter } from "./SentimentMeter";
import { Transcript } from "./Transcript";
import { AISuggestedResponses } from "./AISuggestedResponses";
import { HandoffCopilot } from "./HandoffCopilot";
import { CustomerContextPanel } from "./CustomerContextPanel";
import { ComplianceChecklist } from "./ComplianceChecklist";
import { WrapUpBar } from "./WrapUpBar";
import { HandoffAlerts } from "./HandoffQueue";
import { handoffErrorWords, wrapDraft } from "./handoff-words";
import { useCannedResponses } from "@/api/inbox";
import { can, useMe } from "@/api/me";
import {
  useAcceptSuggestion,
  useClaimHandoff,
  useRecordDisclosure,
  useWrapUpHandoff,
  type ComplianceItem,
  type FiledRecord,
  type HandoffSession,
  type WrapUpPayload,
} from "@/api/handoff";
import { useMinWidth } from "@/hooks/use-min-width";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type RailTab = "context" | "suggest" | "compliance";
const TABS: ReadonlyArray<readonly [RailTab, string]> = [
  ["context", "Context"],
  ["suggest", "Suggest"],
  ["compliance", "Compliance"],
];

/**
 * One case on the follow-up desk. Its holder works it -- ticks, copies, wraps
 * up -- while they may change cases (perm-interactions-write); everyone else
 * who may open it reads it. A supervisor takes a colleague's case over through
 * the same claim, naming whom they saw holding it.
 */
export function HandoffCase({
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
  const canWrite = can(me, "perm-interactions-write");
  const open = session.status !== "completed";
  const pending = session.status === "pending_claim";
  const mine = session.claimed && !monitor;
  const working = mine && open && canWrite;
  const owner = me ? { id: me.id, tenantId: me.tenantId } : undefined;

  // Unsaved notes are the holder's while the case is theirs and open: taken
  // over, or closed by someone else, they go.
  const meId = me?.id;
  const meTenant = me?.tenantId;
  useEffect(() => {
    if ((mine && open) || !meId || !meTenant) return;
    wrapDraft.write({ id: meId, tenantId: meTenant }, session.handoffId, "");
  }, [mine, open, meId, meTenant, session.handoffId]);

  const navigate = useNavigate({ from: "/handoff" });
  const canned = useCannedResponses();
  const wrapMut = useWrapUpHandoff();
  const takeMut = useClaimHandoff();
  const disclose = useRecordDisclosure(session.interactionId);
  const accept = useAcceptSuggestion(session.interactionId);
  const wide = useMinWidth(1024);
  const [wrapOpen, setWrapOpen] = useState(false);
  const [wrapError, setWrapError] = useState<string | null>(null);
  const [railTab, setRailTab] = useState<RailTab>("context");

  const saveWrap = (payload: WrapUpPayload) => {
    setWrapError(null);
    wrapMut.mutate(
      {
        interactionId: session.interactionId,
        handoffId: session.handoffId,
        customerId: session.customerId,
        ...payload,
      },
      {
        onSuccess: () => {
          wrapDraft.write(owner, session.handoffId, "");
          toast.success("Wrap-up saved", {
            action: {
              label: "View case",
              onClick: () => void navigate({ search: { interactionId: session.interactionId } }),
            },
          });
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

  // A reassignment, conditional on who the supervisor saw holding the case.
  const takeOver = () => {
    takeMut.mutate(
      { interactionId: session.interactionId, expectedAssigneeId: activeCall.handlerUserId },
      {
        onSuccess: () => {
          toast.success("Case taken over — it's yours now");
          void navigate({
            search: { interactionId: session.interactionId, customerId: session.customerId },
            replace: true,
          });
        },
        onError: (e) => toast.error(handoffErrorWords(e)),
      },
    );
  };

  const onTabKey = (e: KeyboardEvent) => {
    const at = TABS.findIndex(([key]) => key === railTab);
    const next =
      e.key === "ArrowRight"
        ? (at + 1) % TABS.length
        : e.key === "ArrowLeft"
          ? (at - 1 + TABS.length) % TABS.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? TABS.length - 1
              : -1;
    if (next < 0) return;
    e.preventDefault();
    const key = TABS[next]![0];
    setRailTab(key);
    document.getElementById(`handoff-tabbtn-${key}`)?.focus();
  };

  const copilot = (
    <HandoffCopilot
      interactionId={session.interactionId}
      evidence={session.copilotEvidence}
      canSignal={canSupervise}
    />
  );
  const context = (
    <>
      <HandoffAlerts items={alerts} canAck={canSupervise} />
      <CustomerContextPanel
        call={activeCall}
        context={customerContext}
        canApply={working && can(me, "perm-collections-write")}
        canCapture={working && can(me, "perm-leads-write")}
      />
    </>
  );
  const suggest = (
    <>
      {copilot}
      <AISuggestedResponses
        items={suggestions}
        onUsed={
          working
            ? (id) => accept.mutate(id, { onError: (e) => toast.error(handoffErrorWords(e)) })
            : undefined
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
      readOnly={!working}
    />
  );

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface">
      <CaseHeader
        call={activeCall}
        monitor={monitor}
        onWrapUp={working && !wrapOpen ? () => setWrapOpen(true) : undefined}
      />
      {stale != null ? <StaleBanner at={stale} what="this case" /> : null}
      {mine && open && !canWrite ? (
        <Notice>Your role can no longer change cases, so this one is read-only.</Notice>
      ) : null}
      {!open && session.wrapUp ? (
        <WrapUpSummary wrapUp={session.wrapUp} filed={session.filed} />
      ) : null}
      {pending && !monitor ? (
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-150 border-b border-border bg-background-warning-subtler px-250 py-100">
          <p className="text-body-small text-text">
            {canWrite
              ? "This case is waiting for an agent. Claim it to work it and wrap it up."
              : "This case is waiting for an agent."}
          </p>
          <div className="flex items-center gap-150">
            {claimError ? (
              <p role="alert" className="text-body-small text-text-danger">
                {claimError}
              </p>
            ) : null}
            {canWrite ? (
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
              disabled={takeMut.isPending || claiming}
              onClick={session.claimed ? takeOver : onClaim}
              className="rounded-medium bg-background-danger-bold px-150 py-050 text-body-small font-semibold text-text-inverse hover:bg-background-danger-bold-hovered disabled:opacity-60"
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
            {TABS.map(([key, label]) => (
              <button
                key={key}
                id={`handoff-tabbtn-${key}`}
                type="button"
                role="tab"
                aria-selected={railTab === key}
                aria-controls={`handoff-tab-${key}`}
                tabIndex={railTab === key ? 0 : -1}
                onKeyDown={onTabKey}
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
            aria-labelledby={`handoff-tabbtn-${railTab}`}
            className="max-h-[40vh] space-y-150 overflow-y-auto px-150 py-150"
          >
            {railTab === "context" && context}
            {railTab === "suggest" && suggest}
            {railTab === "compliance" && compliance}
          </div>
        </div>
      ) : null}

      {working ? (
        <WrapUpBar
          open={wrapOpen}
          handoffId={session.handoffId}
          outcomes={session.outcomes}
          saving={wrapMut.isPending}
          error={wrapError}
          defaultPtpAmount={customerContext.nextEmi?.amount}
          owner={owner}
          canFile={can(me, "perm-collections-write")}
          onClose={() => setWrapOpen(false)}
          onSave={saveWrap}
        />
      ) : null}
    </div>
  );
}

const FILED_ROUTE = {
  promise: { to: "/promises", label: "Promise" },
  dispute: { to: "/disputes", label: "Dispute" },
  callback: { to: "/callbacks", label: "Callback" },
} as const;

/** How the case was closed, and the records the wrap-up filed. */
function WrapUpSummary({
  wrapUp,
  filed,
}: {
  wrapUp: NonNullable<HandoffSession["wrapUp"]>;
  filed: FiledRecord[];
}) {
  return (
    <section
      aria-label="Wrap-up"
      className="shrink-0 border-b border-border bg-background-success-subtler px-250 py-100"
    >
      <p className="flex flex-wrap items-center gap-075 text-body-small text-text">
        <CheckCircle2 className="h-3.5 w-3.5 text-text-success" />
        <span className="font-semibold">
          Wrapped up{wrapUp.outcome ? `: ${wrapUp.outcome}` : ""}
        </span>
        {wrapUp.at ? <span className="text-text-subtle">{fmtDateTime(wrapUp.at)}</span> : null}
        {filed.map((record) => {
          const route = FILED_ROUTE[record.kind];
          return (
            <Link
              key={record.id}
              to={route.to}
              search={{ id: record.id }}
              className="font-semibold text-text-brand hover:underline"
            >
              {route.label} {record.id}
            </Link>
          );
        })}
      </p>
      {wrapUp.notes ? (
        <p className="mt-050 whitespace-pre-wrap text-body-small text-text-subtle">
          {wrapUp.notes}
        </p>
      ) : null}
    </section>
  );
}

function Notice({ children }: { children: string }) {
  return (
    <p
      role="status"
      className="shrink-0 border-b border-border bg-background-warning-subtler px-250 py-075 text-body-small text-text"
    >
      {children}
    </p>
  );
}

export function StaleBanner({ at, what }: { at: number; what: string }) {
  const time = new Date(at).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "numeric",
    minute: "2-digit",
  });
  return <Notice>{`Couldn't refresh ${what} — showing it as of ${time}.`}</Notice>;
}
