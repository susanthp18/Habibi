import { useCallback, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { SandboxHeader } from "@/components/sandbox/SandboxHeader";
import { ScenarioList } from "@/components/sandbox/ScenarioList";
import { PersonaCard } from "@/components/sandbox/PersonaCard";
import { ConversationPanel } from "@/components/sandbox/ConversationPanel";
import { InspectorPanel } from "@/components/sandbox/InspectorPanel";
import { PromoteDialog } from "@/components/sandbox/PromoteDialog";
import {
  KB_SNAPSHOTS,
  SCENARIOS,
  classifyIntent,
  estimateSentiment,
  generateBotReply,
  type SandboxTurn,
} from "@/data/sandbox-seed";
import { DEFAULT_GUARDRAILS, VERSION_HISTORY } from "@/data/prompt-studio-seed";

export const Route = createFileRoute("/sandbox")({
  head: () => ({
    meta: [
      { title: "Call Simulation Sandbox — Collections Agent" },
      {
        name: "description",
        content:
          "Safely test the collections bot against synthetic scenarios. Inspect retrieval, intent and sentiment, then promote to production.",
      },
      { property: "og:title", content: "Call Simulation Sandbox" },
      {
        property: "og:description",
        content: "Text or talk to the voice collections bot with a chosen prompt version and KB snapshot.",
      },
    ],
  }),
  component: SandboxPage,
});

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function SandboxPage() {
  const publishedPrompt = VERSION_HISTORY.find((v) => v.status === "published") ?? VERSION_HISTORY[0];
  const [promptVersionId, setPromptVersionId] = useState(publishedPrompt.id);
  const [kbSnapshotId, setKbSnapshotId] = useState(KB_SNAPSHOTS[0].id);
  const [scenarioId, setScenarioId] = useState(SCENARIOS[0].id);
  const [turns, setTurns] = useState<SandboxTurn[]>(() => bootstrap(SCENARIOS[0].id));
  const [scriptIndex, setScriptIndex] = useState(0);
  const [awaiting, setAwaiting] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);

  const scenario = SCENARIOS.find((s) => s.id === scenarioId)!;
  const activePrompt = VERSION_HISTORY.find((v) => v.id === promptVersionId) ?? publishedPrompt;
  const activeKb = KB_SNAPSHOTS.find((k) => k.id === kbSnapshotId)!;

  function bootstrap(sid: string): SandboxTurn[] {
    const s = SCENARIOS.find((x) => x.id === sid)!;
    return [
      { id: makeId(), role: "system", text: `New session · ${s.title}`, ts: Date.now(), systemKind: "info" },
      {
        id: makeId(),
        role: "bot",
        text: s.openingBot.replaceAll("{customer_name}", s.persona.name).replaceAll("{agent_name}", "Priya").replaceAll("{bank_name}", "HDFC Bank"),
        ts: Date.now(),
        chunkIds: [],
        latencyMs: 210,
        tokens: 40,
      },
    ];
  }

  const changeScenario = useCallback((id: string) => {
    setScenarioId(id);
    setTurns(bootstrap(id));
    setScriptIndex(0);
  }, []);

  const reset = useCallback(() => {
    setTurns(bootstrap(scenarioId));
    setScriptIndex(0);
    toast.info("Conversation reset");
  }, [scenarioId]);

  const handleCustomerText = useCallback(
    (text: string, fromScript: boolean) => {
      const intentResult = classifyIntent(text);
      const sentiment = estimateSentiment(text);
      const customerTurn: SandboxTurn = {
        id: makeId(),
        role: "customer",
        text,
        ts: Date.now(),
        intent: intentResult.top,
        intentScores: intentResult.scores,
        sentiment,
      };
      setTurns((prev) => [...prev, customerTurn]);

      // schedule bot reply
      setAwaiting(true);
      const currentTurnIndex = fromScript ? scriptIndex : Math.min(scriptIndex, scenario.turns.length - 1);
      const reply = generateBotReply(
        scenario,
        currentTurnIndex,
        text,
        activePrompt.persona,
        activePrompt.guardrails ?? DEFAULT_GUARDRAILS,
      );
      const delay = reply.latencyMs;
      window.setTimeout(() => {
        setTurns((prev) => {
          const next: SandboxTurn[] = [
            ...prev,
            {
              id: makeId(),
              role: "bot",
              text: reply.text,
              ts: Date.now(),
              chunkIds: reply.chunkIds,
              latencyMs: reply.latencyMs,
              tokens: reply.tokens,
              guardrailFlags: reply.guardrailFlags,
            },
          ];
          if (reply.guardrailFlags.includes("auto-escalate")) {
            next.push({ id: makeId(), role: "system", text: "Auto-escalation triggered · routing to Tier 2", ts: Date.now(), systemKind: "warn" });
          }
          return next;
        });
        setAwaiting(false);
      }, delay);

      if (fromScript) setScriptIndex((i) => i + 1);
    },
    [scenario, activePrompt, scriptIndex],
  );

  const playNext = useCallback(() => {
    const nextTurn = scenario.turns[scriptIndex];
    if (!nextTurn) return;
    handleCustomerText(nextTurn.customer, true);
  }, [scenario, scriptIndex, handleCustomerText]);

  const skipEnd = useCallback(() => {
    // Play remaining scripted turns with staggered delays
    let i = scriptIndex;
    const play = () => {
      if (i >= scenario.turns.length) return;
      handleCustomerText(scenario.turns[i].customer, true);
      i++;
      window.setTimeout(play, 1500);
    };
    play();
  }, [scenario, scriptIndex, handleCustomerText]);

  const exportTranscript = useCallback(() => {
    const payload = {
      exportedAt: new Date().toISOString(),
      scenario: { id: scenario.id, title: scenario.title },
      promptVersion: activePrompt.label,
      kbSnapshot: activeKb.label,
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
  }, [scenario, activePrompt, activeKb, turns]);

  const promote = () => {
    setPromoteOpen(false);
    toast.success(`Promoted ${activePrompt.label} + KB ${activeKb.label} to Production`);
  };

  const canPlayNext = useMemo(() => scriptIndex < scenario.turns.length, [scriptIndex, scenario]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <SandboxHeader
          promptVersionId={promptVersionId}
          onPromptVersion={setPromptVersionId}
          kbSnapshotId={kbSnapshotId}
          onKbSnapshot={setKbSnapshotId}
          scenarioId={scenarioId}
          onScenario={changeScenario}
          onReset={reset}
          onExport={exportTranscript}
          onPromote={() => setPromoteOpen(true)}
        />

        <div className="flex min-h-0 flex-1">
          <ScenarioList activeId={scenarioId} onSelect={changeScenario} />

          <div className="flex min-h-0 flex-1 flex-col">
            <PersonaCard persona={scenario.persona} scenarioTitle={scenario.title} />
            <ConversationPanel
              turns={turns}
              onSend={(t) => handleCustomerText(t, false)}
              onPlayNext={playNext}
              onSkipEnd={skipEnd}
              awaiting={awaiting}
              canPlayNext={canPlayNext}
            />
          </div>

          <InspectorPanel turns={turns} />
        </div>

        <PromoteDialog
          open={promoteOpen}
          onOpenChange={setPromoteOpen}
          promptLabel={activePrompt.label}
          kbLabel={activeKb.label}
          scenarioLabel={scenario.title}
          onConfirm={promote}
        />
      </div>
    </AppShell>
  );
}
