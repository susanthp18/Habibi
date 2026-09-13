import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { SandboxHeader, type SandboxMode } from "@/components/sandbox/SandboxHeader";
import { PersonaCard } from "@/components/sandbox/PersonaCard";
import { ConversationPanel } from "@/components/sandbox/ConversationPanel";
import { InspectorPanel } from "@/components/sandbox/InspectorPanel";
import { PromoteDialog } from "@/components/sandbox/PromoteDialog";
import { TuningStudio } from "@/components/sandbox/TuningStudio";
import { SplitPanes } from "@/components/shared/SplitPanes";
import { useMinWidth } from "@/hooks/use-min-width";
import { useSandboxLiveCall } from "@/components/sandbox/voice/useSandboxLiveCall";
import { EMPTY_INSIGHTS } from "@/components/sandbox/voice/liveEvents";
import { exportInteraction } from "@/api/sandbox";
import { completeSandboxRun } from "@/api/sandbox";
import { fetchVoiceStatus } from "@/api/voice-sandbox";
import { publishPromptVersion } from "@/api/prompt-studio";
import type { IntentKey } from "@/api/types/sandbox";
import { EMPTY_SESSION, sandboxSessionReducer } from "@/components/sandbox/sandboxSession";
import { downloadJson, openingTurns } from "@/components/sandbox/sessionOpening";
import { useTextRehearsal } from "@/components/sandbox/useTextRehearsal";
import { useSandboxSelection, type SandboxSearch } from "@/components/sandbox/useSandboxSelection";
import { LoadingState } from "@/components/ui/loading-state";
import type { AgentTuning } from "@/api/types/agent-tuning";
import { DEFAULT_AGENT_TUNING, tuningFromVoiceConfig } from "@/lib/agent-tuning";

export const Route = createLazyFileRoute("/_app/sandbox")({
  component: SandboxRoute,
});

function SandboxRoute() {
  return <SandboxPage search={Route.useSearch()} />;
}

export function SandboxPage({ search }: { search: SandboxSearch }) {
  const {
    cards,
    botId,
    setBotId,
    skillSlug,
    setSkillSlug,
    versions,
    scenarios,
    kbOptions,
    promptVersionId,
    setPromptVersionId,
    kbSnapshotId,
    setKbSnapshotId,
    setScenarioId,
    scenario,
    activePrompt,
    attachedSkills,
    activeKb,
    loading,
  } = useSandboxSelection(search);
  const [session, dispatch] = useReducer(sandboxSessionReducer, EMPTY_SESSION);
  const { turns, scriptIndex, run, halted, flowNode, textToolCalls, liveMetrics } = session;
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [mode, setMode] = useState<SandboxMode>("text");
  // Declared up here with the other hooks: the panes are assembled after two
  // early returns, and a hook called past those would break the rules-of-hooks
  // ordering on the loading render.
  const isLg = useMinWidth(1024);
  const isXl = useMinWidth(1280);
  const [autoPlayTts, setAutoPlayTts] = useState(false);
  const [tuning, setTuning] = useState<AgentTuning>(DEFAULT_AGENT_TUNING);
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [nextCallDirty, setNextCallDirty] = useState(false);
  const bootstrapped = useRef(false);
  const tuningBaseline = useRef(DEFAULT_AGENT_TUNING);

  useEffect(() => {
    if (!scenario) return;
    if (bootstrapped.current) return;
    dispatch({ type: "start", turns: openingTurns(scenario) });
    bootstrapped.current = true;
  }, [scenario]);

  useEffect(() => {
    // The cursor belongs to the graph it was walked in. Carrying it across a
    // version switch posts card A's node key against card B's graph, which
    // resolves to nothing — or, on a fleet graph where two members own the same
    // local name, to a step in the wrong member.
    dispatch({ type: "clearFlowNode" });
    if (!activePrompt?.voice) return;
    const next = tuningFromVoiceConfig(activePrompt.voice, DEFAULT_AGENT_TUNING);
    setTuning(next);
    tuningBaseline.current = next;
    setNextCallDirty(false);
  }, [activePrompt?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      try {
        const s = await fetchVoiceStatus();
        if (!cancelled) setLiveEnabled(Boolean(s.ok));
      } catch {
        // Both call sites are `void tick()`, so a rejected probe became an
        // unhandled rejection. An unreachable voice service is not live —
        // leaving liveEnabled true offered a call that cannot connect.
        if (!cancelled) setLiveEnabled(false);
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 8000);
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  const { awaiting, handleCustomerText, playNext, skipEnd, canPlayNext } = useTextRehearsal({
    scenario,
    activePrompt,
    kbSnapshotId,
    skillSlug,
    mode,
    session,
    dispatch,
  });

  // A run that was started is completed when the session it belonged to
  // ends -- a reset or a scenario change. It used to stay `running` forever,
  // and the row was written for nothing.
  const closeRun = useCallback(() => {
    if (run && run.status === "running") {
      completeSandboxRun(run.id).catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : "Could not close the sandbox run"),
      );
    }
  }, [run]);

  const changeScenario = useCallback(
    (id: string) => {
      closeRun();
      setScenarioId(id);
      const next = scenarios.find((x) => x.id === id);
      if (next) dispatch({ type: "start", turns: openingTurns(next) });
    },
    [scenarios, closeRun],
  );

  const reset = useCallback(() => {
    if (!scenario) return;
    closeRun();
    dispatch({ type: "start", turns: openingTurns(scenario), clearMetrics: true });
    toast.info("Conversation reset");
  }, [scenario, closeRun]);

  const exportTranscript = useCallback(() => {
    if (!scenario || !activePrompt) return;
    const payload = {
      exportedAt: new Date().toISOString(),
      scenario: { id: scenario.id, title: scenario.title },
      promptVersion: activePrompt.label,
      kbSnapshot: activeKb.label,
      runId: run?.id ?? null,
      tuning,
      turns,
    };
    downloadJson(`sandbox-${scenario.id}-${activePrompt.label}-${Date.now()}.json`, payload);
    toast.success("Transcript exported");
  }, [scenario, activePrompt, activeKb, turns, run, tuning]);

  const live = useSandboxLiveCall({
    enabled: mode === "live",
    promptVersionId: activePrompt?.id ?? "",
    kbSnapshotId: kbSnapshotId === "current" ? null : kbSnapshotId,
    scenarioId: scenario?.id ?? "",
    persona: scenario?.persona ?? {
      name: "Customer",
      phoneLast4: "0000",
      product: "—",
      dpd: 0,
      overdue: 0,
      mood: "neutral",
      language: "English",
    },
    tuning,
    onTurns: (value) => dispatch({ type: "turns", value }),
    onMetrics: (value) => dispatch({ type: "metrics", value }),
  });

  /**
   * The server-assembled record for this call.
   *
   * Distinct from `exportTranscript`, which serialises what the browser holds —
   * turn text and the tuning form. Nothing the reviewer actually needs to judge
   * a call lives in the browser: the per-stage latency split, the tool calls and
   * their arguments, the KB retrievals and the guardrail flags are all
   * server-side, which is why this fetches rather than serialises.
   */
  const exportCallReport = useCallback(
    async (format: "md" | "json") => {
      const id = live.insights.interactionId;
      if (!id) {
        toast.error("No call to export yet — start a live call first");
        return;
      }
      try {
        await exportInteraction(id, format);
        toast.success(format === "md" ? "Call report downloaded" : "Call data downloaded");
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Export failed");
      }
    },
    [live.insights.interactionId],
  );

  const promote = () => {
    setPromoteOpen(false);
    if (!activePrompt) return;
    const snap = kbSnapshotId === "current" ? null : kbSnapshotId;
    void publishPromptVersion(activePrompt.id, `Sandbox promote · ${activeKb.label}`, {
      kbSnapshotId: snap,
    })
      .then(() => {
        toast.success(`Promoted ${activePrompt.label} to Production`, {
          description: `KB: ${activeKb.label} · authored tuning preserved`,
        });
      })
      .catch((err: Error) => toast.error("Promote failed", { description: err.message }));
  };

  const turnsUsed = useMemo(() => turns.filter((t) => t.role === "customer").length, [turns]);
  const turnsMax = useMemo(() => {
    const g = activePrompt?.guardrails?.maxTurns;
    // The server's budget, not a second copy of it.
    const hard = run?.turnBudget ?? 3;
    if (typeof g === "number" && g > 0) return Math.min(hard, g);
    return hard;
  }, [activePrompt, run]);

  const lastExpectedIntent = useMemo((): IntentKey | null => {
    if (!scenario || scriptIndex <= 0) return null;
    return scenario.turns[scriptIndex - 1]?.expectedIntent ?? null;
  }, [scenario, scriptIndex]);

  if (loading && !scenario) {
    return (
      <>
        <div className="grid h-full place-items-center">
          <LoadingState label="Loading sandbox" />
        </div>
      </>
    );
  }

  if (!scenario || !activePrompt) {
    return (
      <>
        <div className="grid h-full place-items-center text-body text-text-danger">
          Couldn’t load scenarios / prompt versions.
        </div>
      </>
    );
  }

  const tuningPane = (
    <TuningStudio
      className="flex w-full"
      value={tuning}
      onChange={(next) => {
        setTuning(next);
        // next-call knobs dirty heuristic: vad/turn/interaction changed
        const base = tuningBaseline.current;
        const dirty =
          JSON.stringify(next.vad) !== JSON.stringify(base.vad) ||
          JSON.stringify(next.turn) !== JSON.stringify(base.turn) ||
          JSON.stringify(next.interaction) !== JSON.stringify(base.interaction) ||
          next.tts.text_aggregation_mode !== base.tts.text_aggregation_mode ||
          next.stt.language !== base.stt.language;
        setNextCallDirty(dirty);
      }}
      onLiveApply={(delta) => {
        void live.applyTune(delta);
      }}
      callLive={mode === "live" && live.status === "live"}
      nextCallDirty={nextCallDirty}
      onRestartCall={() => {
        tuningBaseline.current = tuning;
        setNextCallDirty(false);
        void live.restart();
      }}
    />
  );

  const conversationPane = (
    <div className="flex h-full min-h-0 flex-col">
      <PersonaCard
        persona={scenario.persona}
        scenarioTitle={scenario.title}
        verified={live.insights.verifiedCustomer}
      />
      <ConversationPanel
        mode={mode}
        turns={turns}
        onSend={(t) => void handleCustomerText(t, false)}
        onPlayNext={playNext}
        onSkipEnd={skipEnd}
        awaiting={awaiting}
        canPlayNext={canPlayNext}
        voice={activePrompt.voice}
        autoPlayTts={autoPlayTts}
        onAutoPlayTts={setAutoPlayTts}
        lastExpectedIntent={lastExpectedIntent}
        live={mode === "live" ? live.chrome : null}
      />
    </div>
  );

  const inspectorPane = (
    <InspectorPanel
      className="flex w-full"
      turns={turns}
      metrics={liveMetrics}
      insights={mode === "text" ? { ...EMPTY_INSIGHTS, toolCalls: textToolCalls } : live.insights}
      // Without this the Trace tab silently fell back to its client-derived
      // sketch on every live call, reporting "0 chunks · 0ms · 0t".
      interactionId={live.insights.interactionId}
      runId={run?.id ?? null}
    />
  );

  // Draggable splits, matching Customer 360 and the Inbox. The storage key
  // carries the pane count because SplitPanes discards a persisted layout whose
  // length no longer matches — sharing one key across the 2- and 3-pane
  // breakpoints would silently reset the user's widths on every resize past xl.
  const panes = !isLg ? (
    conversationPane
  ) : isXl ? (
    <SplitPanes
      storageKey="sandbox-split-3"
      defaultWidths={[22, 50, 28]}
      minWidthsPx={[240, 420, 300]}
    >
      {tuningPane}
      {conversationPane}
      {inspectorPane}
    </SplitPanes>
  ) : (
    <SplitPanes storageKey="sandbox-split-2" defaultWidths={[26, 74]} minWidthsPx={[240, 420]}>
      {tuningPane}
      {conversationPane}
    </SplitPanes>
  );

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <SandboxHeader
          mode={mode}
          onMode={(m) => {
            if (m === "live" && !liveEnabled) {
              toast.message("Voice worker not detected yet", {
                description: "You can still open Live mode — Start call needs: python -m voice.bot",
              });
            }
            setMode(m);
          }}
          liveEnabled={liveEnabled}
          cardId={botId}
          editBotId={botId}
          cards={cards}
          onCard={(id) => {
            setBotId(id);
            setPromptVersionId("");
            dispatch({ type: "invalidateRun", clearTools: true });
          }}
          skillSlug={skillSlug}
          // The card's attached packs, not the whole library: a slug the card
          // does not carry is refused by the server (`skill_not_attached`), so
          // offering it here was a rehearsal that quietly ran without it.
          skills={attachedSkills}
          onSkill={setSkillSlug}
          promptVersionId={promptVersionId || activePrompt.id}
          promptVersions={versions}
          onPromptVersion={(id) => {
            setPromptVersionId(id);
            dispatch({ type: "start", turns: openingTurns(scenario) });
          }}
          kbSnapshotId={kbSnapshotId}
          kbSnapshots={kbOptions}
          onKbSnapshot={(id) => {
            setKbSnapshotId(id);
            dispatch({ type: "invalidateRun" });
          }}
          scenarioId={scenario.id}
          scenarios={scenarios}
          onScenario={changeScenario}
          turnsUsed={turnsUsed}
          turnsMax={turnsMax}
          statusLabel={
            mode === "live"
              ? live.status === "live"
                ? "Live"
                : live.status === "connecting"
                  ? "Connecting"
                  : "Live idle"
              : halted
                ? "Text halted"
                : run
                  ? "Text run active"
                  : "Idle"
          }
          onReset={reset}
          onExport={exportTranscript}
          interactionId={live.insights.interactionId}
          onExportReport={exportCallReport}
          onPromote={() => setPromoteOpen(true)}
        />

        <div className="shrink-0 border-b border-border bg-surface-sunken px-150 py-075 text-body-tiny text-text-subtle">
          Rehearsal evidence: {turnsUsed} customer {turnsUsed === 1 ? "turn" : "turns"} — a low
          sample, not a production guarantee. Text tools are simulated with no production side
          effects; text/WhatsApp does not walk the authored flow graph. Verify voice behavior in
          Live mode.
        </div>

        <div className="flex min-h-0 flex-1">{panes}</div>

        <PromoteDialog
          open={promoteOpen}
          onOpenChange={setPromoteOpen}
          promptLabel={activePrompt.label}
          kbLabel={activeKb.label}
          scenarioLabel={scenario.title}
          onConfirm={promote}
        />
      </div>
    </>
  );
}
