import { PromptEditor } from "@/components/prompt-studio/PromptEditor";
import { PersonaSliders } from "@/components/prompt-studio/PersonaSliders";
import { VoicePanel } from "@/components/prompt-studio/VoicePanel";
import { GuardrailsPanel } from "@/components/prompt-studio/GuardrailsPanel";
import type { FlowGraph, FlowIssue } from "@/api/flow";
import type { PromptLintFinding } from "@/api/prompt-studio";
import type { PersonaPreset } from "@/api/types/prompt-studio";
import type { CompileReport } from "@/api/agent-studio";
import type { AgentCard } from "@/api/agent-card";
import type { BotDeployment } from "@/api/prompt-studio";
import type { Dispatch, SetStateAction } from "react";
import { cn } from "@/lib/utils";
import { ShipTab, type ShipState } from "@/components/prompt-studio/ShipTab";
import { BindingsTab } from "@/components/prompt-studio/BindingsTab";
import { ChangeLogTab } from "@/components/prompt-studio/ChangeLogTab";
import {
  AgentGraphTab,
  ConnectorsTab,
  EvalsTab,
  PolicyTab,
  SkillsTab,
  ToolsTab,
} from "@/components/prompt-studio/AgentCardPanels";
import { OutboundTab } from "@/components/prompt-studio/OutboundTab";
import { FILL_TABS, type Tab } from "./PromptStudioShell";
import { FlowTabBody } from "./FlowTabBody";
import type { EditorFields } from "./studioDraft";

/** The one tab on screen, fed from the editor's state and the page's actions. */
export function StudioTabBody({
  tab,
  botId,
  fields,
  set,
  effectiveCard,
  draftId,
  ship,
  setShip,
  activeDeployment,
  priorDeployment,
  compileReport,
  runCompile,
  compileBusy,
  applyPreset,
  presets,
  presetsFailed,
  freshLint,
  lintFailed,
  lintPending,
  cardLocales,
  flowUnreadable,
  loadingBuiltIn,
  setLoadingBuiltIn,
  setReplaceUnreadable,
  onFlowValidation,
  grantTools,
}: {
  tab: Tab;
  botId: string;
  fields: EditorFields;
  set: {
    prompt: (v: string) => void;
    persona: (
      v: EditorFields["persona"] | ((p: EditorFields["persona"]) => EditorFields["persona"]),
    ) => void;
    voice: (v: EditorFields["voice"]) => void;
    guardrails: (v: EditorFields["guardrails"]) => void;
    flow: (v: FlowGraph | null | ((p: FlowGraph | null) => FlowGraph | null)) => void;
    card: (v: AgentCard | null) => void;
  };
  effectiveCard: AgentCard;
  draftId: string | null;
  ship: ShipState;
  setShip: (next: ShipState) => void;
  activeDeployment: BotDeployment | null;
  priorDeployment: BotDeployment | null;
  compileReport: CompileReport | null;
  runCompile: () => void;
  compileBusy: boolean;
  applyPreset: (p: PersonaPreset) => void;
  presets: PersonaPreset[];
  presetsFailed: boolean;
  freshLint: PromptLintFinding[];
  lintFailed: boolean;
  lintPending: boolean;
  cardLocales: string[];
  flowUnreadable: boolean;
  loadingBuiltIn: boolean;
  setLoadingBuiltIn: Dispatch<SetStateAction<boolean>>;
  setReplaceUnreadable: (v: boolean) => void;
  onFlowValidation: (r: { ok: boolean; issues: FlowIssue[] }) => void;
  grantTools: string[] | undefined;
}) {
  const { prompt, persona, voice, guardrails, flow } = fields;
  const setCard = set.card;
  const setPrompt = set.prompt;
  const setPersona = set.persona;
  const setVoice = set.voice;
  const setGuardrails = set.guardrails;
  const setFlow = set.flow;
  return (
    <div
      className={cn(
        "min-h-0 flex-1 p-250",
        // Two scroll models, one per kind of tab, and never both at once.
        //
        // A "fill" tab is a workbench: it owns the viewport, sizes itself
        // to the pane, and scrolls inside its own regions. A document tab
        // is a form: it grows as long as it needs and this container
        // scrolls it. Mixing the two is what produced the nested
        // scrollbars — a page that scrolled *and* panes that scrolled,
        // so reaching a control meant scrolling twice in two directions.
        FILL_TABS.has(tab) ? "overflow-hidden" : "overflow-y-auto",
      )}
    >
      <div className={cn(FILL_TABS.has(tab) && "h-full min-h-0")}>
        {tab === "graph" && (
          <AgentGraphTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
        )}
        {tab === "tools" && (
          <ToolsTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
        )}
        {tab === "skills" && (
          <SkillsTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
        )}
        {tab === "connectors" && (
          <ConnectorsTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
        )}
        {tab === "policy" && <PolicyTab />}
        {tab === "outbound" && (
          <OutboundTab
            botId={botId}
            card={effectiveCard}
            flow={flow}
            onChange={(next) => setCard(next)}
          />
        )}
        {tab === "bindings" && <BindingsTab botId={botId} />}
        {tab === "changelog" && <ChangeLogTab botId={botId} />}
        {tab === "evals" && (
          <EvalsTab
            botId={botId}
            card={effectiveCard}
            onChange={(next) => setCard(next)}
            promptVersionId={draftId ?? undefined}
          />
        )}
        {tab === "ship" && (
          <ShipTab
            botId={botId}
            value={ship}
            onChange={setShip}
            activeDeploymentId={activeDeployment?.id}
            priorDeploymentId={priorDeployment?.id}
            rollbackDeploymentId={activeDeployment?.rollbackDeploymentId}
            compileReport={compileReport}
            onCompile={runCompile}
            compileBusy={compileBusy}
          />
        )}
        {tab === "prompt" && (
          <PromptEditor
            botId={botId}
            value={prompt}
            onChange={setPrompt}
            onApplyPreset={applyPreset}
            presets={presets}
            presetsFailed={presetsFailed}
            lintFindings={freshLint}
            lintFailed={lintFailed}
            lintPending={lintPending}
            // The footer's cost figure is only honest if it can assemble
            // the message the runtime actually sends. Guardrails are most
            // of the difference; persona decides the language line.
            guardrails={guardrails}
            persona={persona}
          />
        )}
        {tab === "persona" && (
          <PersonaSliders
            value={persona}
            onChange={setPersona}
            presets={presets}
            presetsFailed={presetsFailed}
            // Same pipeline PromptEditor gets. Omitted, these chips wrote
            // traits straight to state — no confirmation, no toast, no
            // undo — while the identical chip one tab over did all three.
            onApplyPreset={applyPreset}
            voice={voice}
          />
        )}
        {tab === "voice" && (
          <VoicePanel value={voice} onChange={setVoice} cardLocales={cardLocales} />
        )}
        {tab === "guardrails" && <GuardrailsPanel value={guardrails} onChange={setGuardrails} />}
        {tab === "flow" && (
          <FlowTabBody
            flow={flow}
            setFlow={setFlow}
            flowUnreadable={flowUnreadable}
            loadingBuiltIn={loadingBuiltIn}
            setLoadingBuiltIn={setLoadingBuiltIn}
            setReplaceUnreadable={setReplaceUnreadable}
            onFlowValidation={onFlowValidation}
            grantTools={grantTools}
          />
        )}
      </div>
    </div>
  );
}
