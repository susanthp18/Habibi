import { useEffect, useMemo, useRef, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { CallHeader } from "@/components/handoff/CallHeader";
import { SentimentMeter } from "@/components/handoff/SentimentMeter";
import { LiveTranscript } from "@/components/handoff/LiveTranscript";
import { AISuggestedResponses } from "@/components/handoff/AISuggestedResponses";
import { HandoffCopilot } from "@/components/handoff/HandoffCopilot";
import { CustomerContextPanel } from "@/components/handoff/CustomerContextPanel";
import { ComplianceChecklist } from "@/components/handoff/ComplianceChecklist";
import { WrapUpBar } from "@/components/handoff/WrapUpBar";
import { HandoffAlerts, HandoffQueueList } from "@/components/handoff/HandoffQueue";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { USE_MOCK } from "@/api/config";
import { postSupervisorAction } from "@/api/floor";
import { useCannedResponses } from "@/api/inbox";
import { usePatchPresence } from "@/api/presence";
import {
  acceptHandoffSuggestion,
  postHandoffDisclosure,
  useClaimHandoff,
  useHandoffActive,
  useHandoffQueue,
  useHandoffSession,
  useWrapUpHandoff,
  type HandoffSession,
  type WrapUpPayload,
} from "@/api/handoff";
import type { Suggestion, TranscriptTurn } from "@/data/handoff-seed";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/handoff")({
  component: HandoffPage,
});

const TICK_MS = 500;
type RailTab = "context" | "suggest" | "compliance";

function HandoffPage() {
  const { interactionId, customerId, mode } = Route.useSearch();
  const navigate = useNavigate({ from: "/handoff" });
  const queue = useHandoffQueue(customerId);
  const active = useHandoffActive();
  const claimMut = useClaimHandoff();

  useEffect(() => {
    if (USE_MOCK) return;
    if (interactionId) return;
    const mine = active.data?.interactionId ?? queue.data?.activeInteractionId;
    if (mine) {
      void navigate({ search: { interactionId: mine, customerId }, replace: true });
    }
  }, [interactionId, active.data, queue.data, customerId, navigate]);

  const handleClaim = (id: string) => {
    claimMut.mutate(id, {
      onSuccess: (session) => {
        void navigate({ search: { interactionId: session.interactionId, customerId } });
      },
    });
  };

  if (USE_MOCK) {
    return (
      <AppShell>
        {!active.data ? <HandoffSkeleton /> : <HandoffLive session={active.data} mock />}
      </AppShell>
    );
  }

  if (interactionId) {
    return (
      <AppShell>
        <HandoffSessionGate
          interactionId={interactionId}
          customerId={customerId}
          monitor={mode === "monitor"}
          onClaim={handleClaim}
          claiming={claimMut.isPending}
          claimError={claimMut.error}
        />
      </AppShell>
    );
  }

  if (queue.isError) {
    return (
      <AppShell>
        <div className="grid h-full place-items-center p-400 text-center">
          <p className="text-sm font-semibold text-text">Could not load the handoff queue</p>
          <p className="mt-050 text-body text-text-subtlest">
            {queue.error instanceof Error ? queue.error.message : "The request failed."}
          </p>
          <button
            type="button"
            onClick={() => void queue.refetch()}
            className="mt-150 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-semibold text-white"
          >
            Retry
          </button>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      {!queue.data ? (
        <HandoffSkeleton />
      ) : (
        <HandoffQueueList
          items={queue.data.items}
          claimingId={claimMut.isPending ? claimMut.variables : null}
          onClaim={handleClaim}
        />
      )}
    </AppShell>
  );
}

function HandoffSessionGate({
  interactionId,
  customerId,
  monitor: monitorMode,
  onClaim,
  claiming,
  claimError,
}: {
  interactionId: string;
  customerId?: string;
  monitor?: boolean;
  onClaim: (id: string) => void;
  claiming: boolean;
  claimError: Error | null;
}) {
  const { data: session, isError, error, refetch, isFetching } = useHandoffSession(interactionId, {
    poll: true,
  });

  if (isError) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-150 bg-surface p-300 text-center">
        <p className="text-sm font-semibold text-text">Could not load the handoff session</p>
        <p className="max-w-md text-body text-text-subtlest">
          {error instanceof Error ? error.message : "The request failed."}
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="rounded-medium bg-background-brand-bold px-150 py-100 text-body font-semibold text-white transition-colors hover:bg-background-brand-bold-hovered disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isFetching ? "Retrying…" : "Retry"}
        </button>
      </div>
    );
  }

  if (!session) return <HandoffSkeleton />;

  const monitor = Boolean(monitorMode || session.monitor);

  if (!session.claimed && !monitor) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-150 p-400 text-center">
        <p className="text-sm font-semibold text-text">
          {session.activeCall.customerName} is waiting in queue
        </p>
        <p className="max-w-md text-body text-text-subtlest">
          {session.activeCall.escalationReason} · {session.activeCall.accountId}
        </p>
        {claimError ? (
          <p className="text-body-small text-text-danger">{claimError.message}</p>
        ) : null}
        <button
          type="button"
          disabled={claiming}
          onClick={() => onClaim(interactionId)}
          className="rounded-medium bg-background-brand-bold px-200 py-100 text-body font-semibold text-white hover:bg-background-brand-bold-hovered disabled:opacity-60"
        >
          {claiming ? "Claiming…" : "Claim this call"}
        </button>
      </div>
    );
  }

  return <HandoffLive session={session} customerId={customerId} monitor={monitor} onClaim={onClaim} />;
}

function HandoffSkeleton() {
  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface" aria-busy="true">
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

function HandoffLive({
  session,
  mock,
  customerId: _customerId,
  monitor = false,
  onClaim,
}: {
  session: HandoffSession;
  mock?: boolean;
  customerId?: string;
  monitor?: boolean;
  onClaim?: (id: string) => void;
}) {
  const {
    activeCall,
    customerContext,
    transcriptScript,
    suggestions,
    complianceItems,
    dispositions,
    speakers,
    sentimentSeries,
    alerts,
  } = session;

  const wrapMut = useWrapUpHandoff();
  const presenceMut = usePatchPresence();
  const canned = useCannedResponses();
  const navigate = useNavigate({ from: "/handoff" });
  const [elapsed, setElapsed] = useState(0);
  const [muted, setMuted] = useState(false);
  const [ended, setEnded] = useState(session.status === "completed");
  const [wrapOpen, setWrapOpen] = useState(false);
  const [wrapSaved, setWrapSaved] = useState(false);
  const [wrapError, setWrapError] = useState<string | null>(null);
  const [visibleTurns, setVisibleTurns] = useState<TranscriptTurn[]>(
    mock ? [] : transcriptScript,
  );
  const [insertedTurns, setInsertedTurns] = useState<TranscriptTurn[]>([]);
  const [insertedIds, setInsertedIds] = useState<Set<string>>(new Set());
  const [sentiment, setSentiment] = useState<number[]>(() =>
    sentimentSeries.length
      ? sentimentSeries
      : Array.from({ length: 40 }, (_, i) => -0.05 + Math.sin(i / 6) * 0.05),
  );
  const [compliance, setCompliance] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const item of complianceItems) {
      if (item.checked) init[item.id] = true;
    }
    return init;
  });
  const [railTab, setRailTab] = useState<RailTab>("context");
  const startedAtRef = useRef<number>(activeCall.startedAt || Date.now());

  useEffect(() => {
    if (mock) return;
    setVisibleTurns(transcriptScript);
    if (sentimentSeries.length) setSentiment(sentimentSeries);
    setCompliance((prev) => {
      const next = { ...prev };
      for (const item of complianceItems) {
        if (item.checked) next[item.id] = true;
      }
      return next;
    });
  }, [mock, transcriptScript, sentimentSeries, complianceItems]);

  useEffect(() => {
    if (ended) return;
    if (!mock) {
      const tick = () => {
        const start = activeCall.startedAt || Date.now();
        setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
      };
      tick();
      const iv = window.setInterval(tick, 1000);
      return () => window.clearInterval(iv);
    }
    const iv = window.setInterval(() => {
      const secs = Math.floor((Date.now() - startedAtRef.current) / 1000);
      setElapsed(secs);
      setVisibleTurns((prev) => {
        const revealed = transcriptScript.filter((t) => t.at <= secs);
        if (revealed.length === prev.length) return prev;
        return revealed;
      });
      setSentiment((prev) => {
        const scriptBeat = [...transcriptScript]
          .reverse()
          .find((t) => t.at <= secs && t.sentimentDelta !== undefined);
        const anchor = scriptBeat?.sentimentDelta ?? 0;
        const last = prev[prev.length - 1] ?? 0;
        const target = Math.max(-1, Math.min(1, last + anchor * 0.08 + (Math.random() - 0.5) * 0.04));
        return [...prev.slice(-59), target];
      });
    }, TICK_MS);
    return () => window.clearInterval(iv);
  }, [ended, mock, transcriptScript, activeCall.startedAt]);

  const allTurns = useMemo(() => {
    const byId = new Map<string, TranscriptTurn>();
    for (const t of [...visibleTurns, ...insertedTurns]) byId.set(t.id, t);
    return [...byId.values()].sort((a, b) => a.at - b.at);
  }, [visibleTurns, insertedTurns]);

  const latestSpeaker = allTurns[allTurns.length - 1]?.speaker;
  const nextScripted = mock ? transcriptScript.find((t) => t.at > elapsed) : undefined;
  const streaming = !ended && (mock ? !!nextScripted : session.status === "active");

  useEffect(() => {
    if (!mock) return;
    setCompliance((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const item of complianceItems) {
        if (item.autoAt !== undefined && elapsed >= item.autoAt && !next[item.id]) {
          next[item.id] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [elapsed, complianceItems, mock]);

  const activeSuggestions: Suggestion[] = useMemo(() => {
    return suggestions.filter((s) => {
      if (insertedIds.has(s.id)) return false;
      if ("accepted" in s && (s as Suggestion & { accepted?: boolean }).accepted) return false;
      if (mock) return elapsed >= s.showAfter;
      return true;
    });
  }, [suggestions, elapsed, insertedIds, mock]);

  const handleInsertSuggestion = (s: Suggestion) => {
    setInsertedIds((prev) => new Set(prev).add(s.id));
    setInsertedTurns((prev) => [
      ...prev,
      { id: `ins-${s.id}`, speaker: "agent", text: s.body, at: elapsed },
    ]);
    if (!mock && !s.id.startsWith("canned-")) {
      void acceptHandoffSuggestion(session.interactionId, s.id).catch(() => undefined);
    }
  };

  const handleToggleCompliance = (id: string) => {
    const item = complianceItems.find((c) => c.id === id);
    if (item?.locked) return;
    const next = !compliance[id];
    setCompliance((prev) => ({ ...prev, [id]: next }));
    if (!mock) {
      void postHandoffDisclosure(session.interactionId, {
        itemId: id,
        ruleId: item?.ruleId,
        label: item?.label,
        read: next,
      });
    }
  };

  const handleEndCall = () => {
    setEnded(true);
    setWrapOpen(true);
    if (!mock) void presenceMut.mutate("wrap_up");
  };

  const handleSaveWrap = (payload: WrapUpPayload) => {
    if (mock) {
      setWrapOpen(false);
      setWrapSaved(true);
      return;
    }
    setWrapError(null);
    wrapMut.mutate(
      {
        interactionId: session.interactionId,
        customerId: session.customerId,
        ...payload,
      },
      {
        onSuccess: () => {
          setWrapOpen(false);
          setWrapSaved(true);
          void presenceMut.mutate("available");
        },
        onError: (e) => {
          setWrapError(e instanceof Error ? e.message : "Wrap-up failed");
        },
      },
    );
  };

  const rail = (
    <>
      <HandoffAlerts items={alerts} mock={mock} />
      <HandoffCopilot
        interactionId={session.interactionId}
        onInsert={monitor ? () => undefined : handleInsertSuggestion}
        monitor={monitor}
      />
      <CustomerContextPanel call={activeCall} context={customerContext} />
      <AISuggestedResponses
        items={activeSuggestions}
        onInsert={monitor ? () => undefined : handleInsertSuggestion}
        canned={monitor ? [] : canned.data}
      />
      <ComplianceChecklist
        items={complianceItems}
        checked={compliance}
        onToggle={monitor ? () => undefined : handleToggleCompliance}
      />
    </>
  );

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface">
      <CallHeader
        call={activeCall}
        elapsed={elapsed}
        muted={muted}
        onToggleMute={() => setMuted((m) => !m)}
        onHold={() => {}}
        onTransfer={() => {}}
        onEnd={handleEndCall}
        ended={ended}
        mediaEnabled={false}
        monitor={monitor}
      />
      {monitor && (
        <div className="flex shrink-0 items-center justify-between gap-150 border-b border-border bg-background-brand-subtlest/50 px-250 py-075">
          <p className="text-body-small text-text-brand">
            Monitoring — you are not on this call. Transcript is live; media is not.
          </p>
          <button
            type="button"
            onClick={() => {
              if (!session.claimed && onClaim) {
                onClaim(session.interactionId);
                return;
              }
              void postSupervisorAction(session.interactionId, "barge")
                .then(() => {
                  toast.success("Handoff taken");
                  void navigate({
                    search: { interactionId: session.interactionId, customerId: session.customerId, mode: undefined },
                    replace: true,
                  });
                })
                .catch((e) => toast.error(e instanceof Error ? e.message : "Take over failed"));
            }}
            className="rounded-medium bg-background-danger-bold px-150 py-050 text-body-small font-semibold text-white hover:bg-background-danger-bold-hovered"
          >
            Take over
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <SentimentMeter series={sentiment} />
          <LiveTranscript
            turns={allTurns}
            streaming={streaming}
            latestSpeaker={latestSpeaker}
            speakers={speakers}
          />
        </div>

        <aside className="hidden w-[22.5rem] shrink-0 flex-col gap-150 overflow-y-auto border-l border-border bg-surface px-150 py-150 lg:flex xl:w-[25rem]">
          {rail}
        </aside>
      </div>

      <div className="flex min-h-0 flex-col border-t border-border lg:hidden">
        <div className="flex shrink-0 gap-050 border-b border-border px-150 py-075">
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
        <div className="max-h-[40vh] overflow-y-auto px-150 py-150">
          {railTab === "context" && (
            <>
              <HandoffAlerts items={alerts} mock={mock} />
              <div className="mt-150">
                <CustomerContextPanel call={activeCall} context={customerContext} />
              </div>
            </>
          )}
          {railTab === "suggest" && (
            <div className="space-y-150">
              <HandoffCopilot
                interactionId={session.interactionId}
                onInsert={handleInsertSuggestion}
                monitor={monitor}
              />
              <AISuggestedResponses
                items={activeSuggestions}
                onInsert={handleInsertSuggestion}
                canned={canned.data}
              />
            </div>
          )}
          {railTab === "compliance" && (
            <ComplianceChecklist
              items={complianceItems}
              checked={compliance}
              onToggle={monitor ? () => undefined : handleToggleCompliance}
            />
          )}
        </div>
      </div>

      {!monitor && (
      <WrapUpBar
        open={wrapOpen}
        saved={wrapSaved}
        saving={wrapMut.isPending}
        error={wrapError}
        dispositions={dispositions}
        defaultNotes={mock ? "Payment gateway failure confirmed. PTP captured." : ""}
        defaultPtpAmount={customerContext.nextEmi?.amount}
        onClose={() => {
          setWrapOpen(false);
          if (wrapSaved) setWrapSaved(false);
        }}
        onSave={handleSaveWrap}
      />
      )}
    </div>
  );
}
