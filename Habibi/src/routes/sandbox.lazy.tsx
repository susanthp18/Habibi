import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { SandboxHeader, type SandboxMode } from "@/components/sandbox/SandboxHeader";
import { PersonaCard } from "@/components/sandbox/PersonaCard";
import { ConversationPanel } from "@/components/sandbox/ConversationPanel";
import { InspectorPanel } from "@/components/sandbox/InspectorPanel";
import { PromoteDialog } from "@/components/sandbox/PromoteDialog";
import { TuningStudio } from "@/components/sandbox/TuningStudio";
import { useSandboxLiveCall } from "@/components/sandbox/voice/useSandboxLiveCall";
import type { TurnMetric } from "@/components/sandbox/inspector/MetricsTab";
import {
  appendSandboxTurn,
  createSandboxRun,
  isIntentKey,
  useSandboxScenarios,
  type SandboxChunkHit,
  type SandboxHistoryItem,
  type SandboxRun,
} from "@/api/sandbox";
import { fetchVoiceStatus } from "@/api/voice-sandbox";
import { usePromptVersions, publishPromptVersion } from "@/api/prompt-studio";
import { useKbSnapshots } from "@/api/kb";
import { type IntentKey, type SandboxTurn } from "@/data/sandbox-seed";
import {
  DEFAULT_AGENT_TUNING,
  tuningFromVoiceConfig,
  type AgentTuning,
} from "@/data/agent-tuning";

export const Route = createLazyFileRoute("/sandbox")({
  component: SandboxPage,
});

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function SandboxPage() {
  const { promptVersionId: searchPromptId } = Route.useSearch();
  const versionsQuery = usePromptVersions();
  const scenariosQuery = useSandboxScenarios();
  const snapshotsQuery = useKbSnapshots();

  const versions = versionsQuery.data ?? [];
  const scenarios = scenariosQuery.data ?? [];
  const kbOptions = useMemo(() => {
    const rows = snapshotsQuery.data ?? [];
    return [
      { id: "current", label: "Current (live index)" },
      ...rows.map((s) => ({ id: s.id, label: s.label || s.id })),
    ];
  }, [snapshotsQuery.data]);

  const publishedPrompt =
    versions.find((v) => v.status === "published") ?? versions[0] ?? null;

  const [promptVersionId, setPromptVersionId] = useState<string>("");
  const [kbSnapshotId, setKbSnapshotId] = useState("current");
  const [scenarioId, setScenarioId] = useState<string>("");
  const [turns, setTurns] = useState<SandboxTurn[]>([]);
  const [scriptIndex, setScriptIndex] = useState(0);
  const [awaiting, setAwaiting] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [run, setRun] = useState<SandboxRun | null>(null);
  const [halted, setHalted] = useState(false);
  const [mode, setMode] = useState<SandboxMode>("text");
  const [autoPlayTts, setAutoPlayTts] = useState(false);
  const [tuning, setTuning] = useState<AgentTuning>(DEFAULT_AGENT_TUNING);
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [liveMetrics, setLiveMetrics] = useState<TurnMetric[]>([]);
  const [nextCallDirty, setNextCallDirty] = useState(false);
  const bootstrapped = useRef(false);
  const tuningBaseline = useRef(DEFAULT_AGENT_TUNING);

  useEffect(() => {
    if (!versions.length) return;
    if (searchPromptId && versions.some((v) => v.id === searchPromptId)) {
      setPromptVersionId(searchPromptId);
      return;
    }
    if (!promptVersionId) {
      setPromptVersionId(publishedPrompt?.id ?? versions[0]!.id);
    }
  }, [versions, searchPromptId, publishedPrompt, promptVersionId]);

  useEffect(() => {
    if (!scenarios.length) return;
    if (!scenarioId) setScenarioId(scenarios[0]!.id);
  }, [scenarios, scenarioId]);

  const scenario = scenarios.find((s) => s.id === scenarioId) ?? scenarios[0];
  const activePrompt =
    versions.find((v) => v.id === promptVersionId) ?? publishedPrompt ?? versions[0];
  const activeKb = kbOptions.find((k) => k.id === kbSnapshotId) ?? kbOptions[0]!;

  const bootstrapLocal = useCallback(
    (sid: string): SandboxTurn[] => {
      const s = scenarios.find((x) => x.id === sid);
      if (!s) return [];
      const opening = (s.openingBot || "")
        .replaceAll("{customer_name}", s.persona.name)
        .replaceAll("{agent_name}", "Priya")
        .replaceAll("{bank_name}", "HDFC Bank")
        .replaceAll("{language}", s.persona.language);
      return [
        {
          id: makeId(),
          role: "system",
          text: `New session · ${s.title}`,
          ts: Date.now(),
          systemKind: "info",
        },
        {
          id: makeId(),
          role: "bot",
          text:
            opening ||
            `Hello, this is Priya from HDFC Bank. Am I speaking with ${s.persona.name}?`,
          ts: Date.now(),
          chunkIds: [],
          latencyMs: 0,
          tokens: 0,
        },
      ];
    },
    [scenarios],
  );

  useEffect(() => {
    if (!scenario) return;
    if (bootstrapped.current) return;
    setTurns(bootstrapLocal(scenario.id));
    setScriptIndex(0);
    setRun(null);
    setHalted(false);
    bootstrapped.current = true;
  }, [scenario, bootstrapLocal]);

  useEffect(() => {
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
      const s = await fetchVoiceStatus();
      if (!cancelled) setLiveEnabled(Boolean(s.ok));
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

  const changeScenario = useCallback(
    (id: string) => {
      setScenarioId(id);
      setTurns(bootstrapLocal(id));
      setScriptIndex(0);
      setRun(null);
      setHalted(false);
    },
    [bootstrapLocal],
  );

  const reset = useCallback(() => {
    if (!scenario) return;
    setTurns(bootstrapLocal(scenario.id));
    setScriptIndex(0);
    setRun(null);
    setHalted(false);
    setLiveMetrics([]);
    toast.info("Conversation reset");
  }, [scenario, bootstrapLocal]);

  const ensureRun = useCallback(async (): Promise<SandboxRun> => {
    if (run && run.status === "running") return run;
    if (!scenario || !activePrompt) throw new Error("Scenario / prompt not ready");
    const created = await createSandboxRun({
      promptVersionId: activePrompt.id,
      scenarioId: scenario.id,
      scenarioTitle: scenario.title,
      kbSnapshotId: kbSnapshotId === "current" ? null : kbSnapshotId,
      openingTemplate: scenario.openingBot,
      persona: scenario.persona,
    });
    setRun(created);
    if (created.openingMessage) {
      setTurns((prev) => {
        const withoutOpening = prev.filter((t) => t.role !== "bot");
        const system = withoutOpening.find((t) => t.role === "system");
        return [
          system ?? {
            id: makeId(),
            role: "system" as const,
            text: `New session · ${scenario.title}`,
            ts: Date.now(),
            systemKind: "info" as const,
          },
          {
            id: makeId(),
            role: "bot" as const,
            text: created.openingMessage!,
            ts: Date.now(),
            chunkIds: [],
            latencyMs: 0,
            tokens: 0,
          },
        ];
      });
    }
    return created;
  }, [run, scenario, activePrompt, kbSnapshotId]);

  const handleCustomerText = useCallback(
    async (text: string, fromScript: boolean) => {
      if (!scenario || !activePrompt || halted || mode !== "text") return;
      setAwaiting(true);
      try {
        const activeRun = await ensureRun();
        const history: SandboxHistoryItem[] = turns
          .filter((t) => t.role === "bot" || t.role === "customer")
          .map((t) => ({ role: t.role as "bot" | "customer", text: t.text }));

        const result = await appendSandboxTurn({
          runId: activeRun.id,
          text,
          history,
          scenario,
          turnIndex: fromScript
            ? scriptIndex
            : Math.min(scriptIndex, Math.max(0, scenario.turns.length - 1)),
          personaState: activePrompt.persona,
          guardrails: activePrompt.guardrails,
        });

        const intentKey = isIntentKey(result.customerTurn.intent)
          ? result.customerTurn.intent
          : undefined;
        const customerTurn: SandboxTurn = {
          id: result.customerTurn.id,
          role: "customer",
          text: result.customerTurn.text,
          ts: Date.now(),
          intent: intentKey,
          intentScores: result.customerTurn.intentScores as SandboxTurn["intentScores"],
          sentiment: result.customerTurn.sentiment,
        };
        const chunks: SandboxChunkHit[] = result.botTurn.chunks ?? [];
        const botTurn: SandboxTurn = {
          id: result.botTurn.id,
          role: "bot",
          text: result.botTurn.text,
          ts: Date.now(),
          chunkIds: result.botTurn.chunkIds,
          chunks,
          latencyMs: result.botTurn.latencyMs,
          tokens: result.botTurn.tokens,
          guardrailFlags: result.botTurn.guardrailFlags,
        };

        setTurns((prev) => {
          const next = [...prev, customerTurn, botTurn];
          if (result.botTurn.guardrailFlags.includes("auto-escalate")) {
            next.push({
              id: makeId(),
              role: "system",
              text: "Auto-escalation triggered · routing to Tier 2",
              ts: Date.now(),
              systemKind: "warn",
            });
          }
          if (result.botTurn.halted) {
            next.push({
              id: makeId(),
              role: "system",
              text: `Run halted · guardrail ${result.botTurn.guardrailFlags.join(", ")}`,
              ts: Date.now(),
              systemKind: "warn",
            });
          }
          return next;
        });

        if (result.botTurn.halted) {
          setHalted(true);
          setRun((r) => (r ? { ...r, status: "completed" } : r));
        }
        if (fromScript) setScriptIndex((i) => i + 1);
        return !result.botTurn.halted;
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Sandbox turn failed");
        return false;
      } finally {
        setAwaiting(false);
      }
    },
    [scenario, activePrompt, halted, ensureRun, turns, scriptIndex, mode],
  );

  const playNext = useCallback(() => {
    if (!scenario) return;
    const nextTurn = scenario.turns[scriptIndex];
    if (!nextTurn) return;
    void handleCustomerText(nextTurn.customer, true);
  }, [scenario, scriptIndex, handleCustomerText]);

  const skipEnd = useCallback(() => {
    if (!scenario || awaiting || halted) return;
    const remaining = scenario.turns.slice(scriptIndex, scriptIndex + 3).map((t) => t.customer);
    if (remaining.length === 0) return;
    void (async () => {
      for (const text of remaining) {
        const ok = await handleCustomerText(text, true);
        if (!ok) break;
      }
    })();
  }, [scenario, scriptIndex, awaiting, halted, handleCustomerText]);

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
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sandbox-${scenario.id}-${activePrompt.label}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
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
    onTurns: setTurns,
    onMetrics: setLiveMetrics,
  });

  const promote = () => {
    setPromoteOpen(false);
    if (!activePrompt) return;
    const snap = kbSnapshotId === "current" ? null : kbSnapshotId;
    void publishPromptVersion(activePrompt.id, `Sandbox promote · ${activeKb.label}`, {
      kbSnapshotId: snap,
      tuning,
    })
      .then(() => {
        toast.success(`Promoted ${activePrompt.label} to Production`, {
          description: `KB: ${activeKb.label} · tuning pinned in deployment bundle`,
        });
      })
      .catch((err: Error) => toast.error("Promote failed", { description: err.message }));
  };

  const canPlayNext = useMemo(() => {
    if (!scenario || halted || awaiting || mode !== "text") return false;
    return scriptIndex < scenario.turns.length;
  }, [scriptIndex, scenario, halted, awaiting, mode]);

  const turnsUsed = useMemo(() => turns.filter((t) => t.role === "customer").length, [turns]);
  const turnsMax = useMemo(() => {
    const g = activePrompt?.guardrails?.maxTurns;
    const hard = 3;
    if (typeof g === "number" && g > 0) return Math.min(hard, g);
    return hard;
  }, [activePrompt]);

  const lastExpectedIntent = useMemo((): IntentKey | null => {
    if (!scenario || scriptIndex <= 0) return null;
    return scenario.turns[scriptIndex - 1]?.expectedIntent ?? null;
  }, [scenario, scriptIndex]);

  const loading = scenariosQuery.isLoading || versionsQuery.isLoading;

  if (loading && !scenario) {
    return (
      <AppShell>
        <div className="grid h-full place-items-center text-[13px] text-text-muted">
          Loading sandbox…
        </div>
      </AppShell>
    );
  }

  if (!scenario || !activePrompt) {
    return (
      <AppShell>
        <div className="grid h-full place-items-center text-[13px] text-danger">
          Couldn’t load scenarios / prompt versions.
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
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
          liveEnabled={true}
          promptVersionId={promptVersionId || activePrompt.id}
          promptVersions={versions}
          onPromptVersion={(id) => {
            setPromptVersionId(id);
            setRun(null);
            setHalted(false);
            setTurns(bootstrapLocal(scenario.id));
            setScriptIndex(0);
          }}
          kbSnapshotId={kbSnapshotId}
          kbSnapshots={kbOptions}
          onKbSnapshot={(id) => {
            setKbSnapshotId(id);
            setRun(null);
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
          onPromote={() => setPromoteOpen(true)}
        />

        <div className="flex min-h-0 flex-1">
          <TuningStudio
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

          <div className="flex min-h-0 flex-1 flex-col">
            <PersonaCard persona={scenario.persona} scenarioTitle={scenario.title} />
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

          <InspectorPanel turns={turns} metrics={liveMetrics} insights={live.insights} />
        </div>

        <PromoteDialog
          open={promoteOpen}
          onOpenChange={setPromoteOpen}
          promptLabel={activePrompt.label}
          kbLabel={activeKb.label}
          scenarioLabel={scenario.title}
          tuningSummary={`${tuning.tts.style} · temp ${tuning.llm.temperature}`}
          onConfirm={promote}
        />
      </div>
    </AppShell>
  );
}
