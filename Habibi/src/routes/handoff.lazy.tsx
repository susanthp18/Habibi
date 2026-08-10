import { useEffect, useMemo, useRef, useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { CallHeader } from "@/components/handoff/CallHeader";
import { SentimentMeter } from "@/components/handoff/SentimentMeter";
import { LiveTranscript } from "@/components/handoff/LiveTranscript";
import { AISuggestedResponses } from "@/components/handoff/AISuggestedResponses";
import { CustomerContextPanel } from "@/components/handoff/CustomerContextPanel";
import { ComplianceChecklist } from "@/components/handoff/ComplianceChecklist";
import { WrapUpBar } from "@/components/handoff/WrapUpBar";
import { Skeleton } from "@/components/ui/skeleton";
import { USE_MOCK } from "@/api/config";
import { useHandoffSession, type HandoffSession } from "@/api/handoff";
import type { Suggestion, TranscriptTurn } from "@/data/handoff-seed";

export const Route = createLazyFileRoute("/handoff")({
  component: HandoffPage,
});

const TICK_MS = 500;

function HandoffPage() {
  const { data: session, isError, error, refetch, isFetching } = useHandoffSession();

  // A failed fetch used to render the skeleton forever: an agent taking a
  // handoff saw a loading screen with no indication anything was wrong and no
  // way to retry.
  if (isError) {
    return (
      <AppShell>
        <div className="flex h-full w-full flex-col items-center justify-center gap-150 bg-surface p-300 text-center">
          <p className="text-sm font-semibold text-text">
            Could not load the handoff session
          </p>
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
      </AppShell>
    );
  }

  return (
    <AppShell>
      {!session ? <HandoffSkeleton /> : <HandoffLive session={session} />}
    </AppShell>
  );
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

function HandoffLive({ session }: { session: HandoffSession }) {
  const { activeCall, customerContext, transcriptScript, suggestions, complianceItems, dispositions } =
    session;

  const [elapsed, setElapsed] = useState(0);
  const [muted, setMuted] = useState(false);
  const [ended, setEnded] = useState(false);
  const [wrapOpen, setWrapOpen] = useState(false);
  const [wrapSaved, setWrapSaved] = useState(false);
  const [visibleTurns, setVisibleTurns] = useState<TranscriptTurn[]>([]);
  const [insertedTurns, setInsertedTurns] = useState<TranscriptTurn[]>([]);
  const [insertedIds, setInsertedIds] = useState<Set<string>>(new Set());
  const [sentiment, setSentiment] = useState<number[]>(() =>
    Array.from({ length: 40 }, (_, i) => -0.05 + Math.sin(i / 6) * 0.05),
  );
  const [compliance, setCompliance] = useState<Record<string, boolean>>({});

  const startedAtRef = useRef<number>(Date.now());

  // Clock + transcript ticker — scripted simulation only in mock mode.
  useEffect(() => {
    if (ended) return;
    if (!USE_MOCK) {
      // Live: show full transcript snapshot immediately; no client script replay.
      setVisibleTurns(transcriptScript);
      setElapsed(Math.max(0, ...transcriptScript.map((t) => t.at), 0));
      return;
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
  }, [ended, transcriptScript]);

  const allTurns = useMemo(() => {
    return [...visibleTurns, ...insertedTurns].sort((a, b) => a.at - b.at);
  }, [visibleTurns, insertedTurns]);

  const latestSpeaker = allTurns[allTurns.length - 1]?.speaker;
  const nextScripted = transcriptScript.find((t) => t.at > elapsed);
  const streaming = !ended && !!nextScripted;

  // Auto-check compliance items at scripted timestamps (mock only).
  useEffect(() => {
    if (!USE_MOCK) {
      // Live mode has no per-item completion source yet (GET /handoff/active
      // returns the item list, not their state), so leave them unchecked for
      // the agent to tick. Marking every item complete asserted that the
      // recording disclosure and identity verification had happened when
      // nothing had confirmed either — the exact claim this checklist exists
      // to substantiate.
      return;
    }
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
  }, [elapsed, complianceItems]);

  // Show suggestions that have "hit" their showAfter timestamp, hide once used
  const activeSuggestions: Suggestion[] = useMemo(() => {
    return suggestions.filter((s) => elapsed >= s.showAfter && !insertedIds.has(s.id));
  }, [suggestions, elapsed, insertedIds]);

  const handleInsertSuggestion = (s: Suggestion) => {
    setInsertedIds((prev) => new Set(prev).add(s.id));
    setInsertedTurns((prev) => [
      ...prev,
      {
        id: `ins-${s.id}`,
        speaker: "agent",
        text: s.body,
        at: elapsed,
      },
    ]);
  };

  const handleToggleCompliance = (id: string) => {
    setCompliance((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleEndCall = () => {
    setEnded(true);
    setWrapOpen(true);
  };

  const handleSaveWrap = () => {
    setWrapOpen(false);
    setWrapSaved(true);
  };

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
      />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* LEFT — sentiment + transcript */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <SentimentMeter series={sentiment} />
          <LiveTranscript turns={allTurns} streaming={streaming} latestSpeaker={latestSpeaker} />
        </div>

        {/* RIGHT rail */}
        <aside className="hidden w-[22.5rem] shrink-0 flex-col gap-150 overflow-y-auto border-l border-border bg-surface px-150 py-150 lg:flex xl:w-[25rem]">
          <CustomerContextPanel call={activeCall} context={customerContext} />
          <AISuggestedResponses items={activeSuggestions} onInsert={handleInsertSuggestion} />
          <ComplianceChecklist
            items={complianceItems}
            checked={compliance}
            onToggle={handleToggleCompliance}
          />
        </aside>
      </div>

      <WrapUpBar
        open={wrapOpen}
        saved={wrapSaved}
        dispositions={dispositions}
        onClose={() => {
          setWrapOpen(false);
          setWrapSaved(false);
        }}
        onSave={handleSaveWrap}
      />
    </div>
  );
}
