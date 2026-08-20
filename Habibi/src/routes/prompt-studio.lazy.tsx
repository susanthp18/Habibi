import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { StudioHeader } from "@/components/prompt-studio/StudioHeader";
import { PromptEditor } from "@/components/prompt-studio/PromptEditor";
import { PersonaSliders } from "@/components/prompt-studio/PersonaSliders";
import { VoicePanel } from "@/components/prompt-studio/VoicePanel";
import { GuardrailsPanel } from "@/components/prompt-studio/GuardrailsPanel";
import { Button } from "@/components/ui/button";
import { FlowCanvas } from "@/components/flow/FlowCanvas";
import {
  emptyGraph,
  fetchBuiltInFlow,
  isEmptyGraph,
  validateFlow,
  type FlowGraph,
  type FlowIssue,
} from "@/api/flow";
import { VersionHistory } from "@/components/prompt-studio/VersionHistory";
import { DiffModal } from "@/components/prompt-studio/DiffModal";
import { PublishDialog } from "@/components/prompt-studio/PublishDialog";
import {
  useActiveProdDeployment,
  useDiscardPromptVersion,
  useEnsureStudioDraft,
  useLintPrompt,
  usePersonaPresets,
  useProdDeployments,
  usePromptVersions,
  usePublishStudioDraft,
  useRestorePromptVersionAsDraft,
  useRollbackBotDeployment,
  type PromptLintFinding,
} from "@/api/prompt-studio";
import {
  DEFAULT_GUARDRAILS,
  DEFAULT_PERSONA,
  DEFAULT_VOICE,
  nextVersionLabel,
  type Guardrails,
  type PersonaPreset,
  type PersonaState,
  type PromptVersion,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import { FileText, Sparkles, Volume2, ShieldAlert, Workflow, Wrench, Lock, FlaskConical, GitBranch, Layers, Plug, Rocket } from "lucide-react";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/ui/loading-state";
import { useAgentStudioCard, useCompileCard, type CompileReport } from "@/api/agent-studio";
import { ShipTab, type ShipState } from "@/components/prompt-studio/ShipTab";
import {
  AgentGraphTab,
  ConnectorsTab,
  EvalsTab,
  PolicyTab,
  SkillsTab,
  ToolsTab,
} from "@/components/prompt-studio/AgentCardPanels";

export const Route = createLazyFileRoute("/prompt-studio")({
  component: function PromptStudioRedirected() {
    const { unansweredId, note } = Route.useSearch();
    return <PromptStudioPage botId="kaia-v2-4" unansweredId={unansweredId} note={note} />;
  },
});

type Tab =
  | "prompt"
  | "flow"
  | "graph"
  | "persona"
  | "voice"
  | "guardrails"
  | "tools"
  | "skills"
  | "connectors"
  | "policy"
  | "evals"
  | "ship";
type SaveStatus = "idle" | "saving" | "saved" | "error";

type AgentCard = Record<string, unknown>;

/** Non-empty object, or null. `{}` is "no card", not "a card with no fields". */
function asCard(value: unknown): AgentCard | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.keys(value as AgentCard).length ? (value as AgentCard) : null;
}

function fingerprint(
  p: string,
  persona: PersonaState,
  voice: VoiceConfig,
  g: Guardrails,
  flow: FlowGraph | null,
  card: AgentCard | null,
) {
  return JSON.stringify({ p, persona, voice, g, flow, card });
}

export function PromptStudioPage({
  botId,
  unansweredId,
  note: gapNote,
}: {
  botId: string;
  unansweredId?: string;
  note?: string;
}) {
  const navigate = useNavigate();
  const [gapBannerDismissed, setGapBannerDismissed] = useState(false);
  const versionsQuery = usePromptVersions(botId);
  const presetsQuery = usePersonaPresets();
  const activeDepQuery = useActiveProdDeployment(botId);
  const prodDepsQuery = useProdDeployments(botId);
  const cardQuery = useAgentStudioCard(botId);
  const compileMutation = useCompileCard(botId);
  const publishMutation = usePublishStudioDraft();
  const restoreMutation = useRestorePromptVersionAsDraft();
  const ensureDraftMutation = useEnsureStudioDraft();
  const discardMutation = useDiscardPromptVersion();
  const rollbackMutation = useRollbackBotDeployment();
  const lintMutation = useLintPrompt();
  const ensureDraft = ensureDraftMutation.mutateAsync;

  const [history, setHistory] = useState<PromptVersion[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string>("");
  const [persona, setPersona] = useState<PersonaState>(DEFAULT_PERSONA);
  const [voice, setVoice] = useState<VoiceConfig>(DEFAULT_VOICE);
  const [guardrails, setGuardrails] = useState<Guardrails>(DEFAULT_GUARDRAILS);
  const [activePresetId, setActivePresetId] = useState<string>("custom");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [lintFindings, setLintFindings] = useState<PromptLintFinding[]>([]);
  // What produced them. The panel used to be cleared by the textarea's own
  // onChange, which covered typing and nothing else — so toggling
  // alwaysDiscloseRecording in the Guardrails tab left a
  // "missing_recording_disclosure" error on screen for a prompt that no longer
  // had that rule, and turning it *on* showed a clean panel. The lint is a
  // function of prompt *and* guardrails; comparing against both is the version
  // that cannot be forgotten when a third input is added.
  const [lintedFp, setLintedFp] = useState<string | null>(null);
  // null until the version loads, so an autosave that fires before the flow is
  // known omits it entirely rather than overwriting a stored graph with {}.
  const [flow, setFlow] = useState<FlowGraph | null>(null);
  const [flowValid, setFlowValid] = useState(true);
  const [flowIssues, setFlowIssues] = useState<FlowIssue[]>([]);
  // The Agent Card is an editor field like the prompt, not a side-channel: the
  // Skills/Tools/Connectors tabs used to PATCH it straight to the server while
  // the editor kept reading the published row, so every toggle snapped back —
  // and a card-only edit was orphaned when publish created its own draft.
  const [card, setCard] = useState<AgentCard | null>(null);
  const [loadingBuiltIn, setLoadingBuiltIn] = useState(false);

  const [tab, setTab] = useState<Tab>("prompt");
  const tabStripRef = useRef<HTMLDivElement>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffBase, setDiffBase] = useState<PromptVersion | undefined>();
  const [publishOpen, setPublishOpen] = useState(false);
  const [compileReport, setCompileReport] = useState<CompileReport | null>(null);
  // Ship settings for a bot with no Agent Card. An authored card keeps them in
  // `card.experiment` instead — see `ship` below.
  const [legacyShip, setLegacyShip] = useState<ShipState>({
    trafficPct: 100,
    shadow: false,
    autoRollback: [],
  });

  useEffect(() => {
    setHydrated(false);
    setDraftId(null);
    setCard(null);
    setCompileReport(null);
  }, [botId]);

  // A scrollable strip can leave the selected tab off-screen — after a publish
  // lands on Ship, or when the tab is restored on a narrow window. Bring it
  // back into view rather than leaving the user looking at a strip with no
  // visible selection.
  useEffect(() => {
    tabStripRef.current
      ?.querySelector<HTMLElement>(`[data-tab="${tab}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);

  const lastSavedFp = useRef<string>("");
  const autosaveTimer = useRef<number | null>(null);
  const skipAutosave = useRef(false);
  // A save already in flight, and a request to run one more when it lands.
  // Without these the 1200ms debounce can fire again while the first
  // `ensureDraft` is still creating the draft — `draftId` is still null, so the
  // second call creates a *second* draft and the version rail grows a duplicate
  // for a single edit.
  const savingRef = useRef(false);
  const resaveRef = useRef(false);
  const [autosaveNonce, setAutosaveNonce] = useState(0);
  // Bumped whenever the saved baseline moves, so `unsaved` below — which reads
  // a ref — is recomputed on the render that follows a save.
  const [savedTick, setSavedTick] = useState(0);
  const markSaved = useCallback((fp: string) => {
    lastSavedFp.current = fp;
    setSavedTick((t) => t + 1);
  }, []);

  // The API, not a hardcoded copy. `?? PRESETS` made an empty persona_presets
  // table look populated — and the rows only ever existed in a migration that
  // a fresh install stamps rather than replays, so a new database showed four
  // presets that were not there and applied templates from nowhere.
  const presets = presetsQuery.data ?? [];
  const showGapBanner = Boolean((gapNote || unansweredId) && !gapBannerDismissed);
  const activeDeployment = activeDepQuery.data ?? null;
  const priorDeployment = useMemo(() => {
    const rows = prodDepsQuery.data ?? [];
    if (activeDeployment?.rollbackDeploymentId) {
      return rows.find((d) => d.id === activeDeployment.rollbackDeploymentId) ?? null;
    }
    return rows.find((d) => d.status === "retired" || d.status === "rolled_back") ?? null;
  }, [prodDepsQuery.data, activeDeployment]);

  // Hydrate editor from published once; keep history in sync with query refetches.
  useEffect(() => {
    if (!versionsQuery.data) return;
    if (!versionsQuery.data.length) {
      // A bot row with no prompt version at all. This used to return early, so
      // `hydrated` stayed false forever and autosave never ran — you could type
      // into the editor and nothing was saved, with no error. Seed the defaults
      // instead so the first version can actually be authored.
      if (!hydrated) {
        skipAutosave.current = true;
        setHistory([]);
        setPrompt("");
        setPersona(DEFAULT_PERSONA);
        setVoice(DEFAULT_VOICE);
        setGuardrails(DEFAULT_GUARDRAILS);
        setFlow(null);
        setCard(asCard(cardQuery.data?.agentCard));
        setDraftId(null);
        markSaved("");
        setHydrated(true);
        window.setTimeout(() => {
          skipAutosave.current = false;
        }, 0);
      }
      return;
    }
    setHistory(versionsQuery.data);
    if (!hydrated) {
      const live =
        versionsQuery.data.find((v) => v.status === "published") ?? versionsQuery.data[0];
      // Prefer newest draft if present (resume work after refresh).
      const newestDraft = versionsQuery.data.find((v) => v.status === "draft");
      const start = newestDraft ?? live;
      skipAutosave.current = true;
      setPrompt(start.prompt);
      setPersona(start.persona ?? DEFAULT_PERSONA);
      setVoice(start.voice ?? DEFAULT_VOICE);
      setGuardrails(start.guardrails ?? DEFAULT_GUARDRAILS);
      setFlow(start.flow ?? null);
      setCard(asCard(start.agentCard));
      setDraftId(newestDraft?.id ?? null);
      markSaved(fingerprint(
        start.prompt,
        start.persona ?? DEFAULT_PERSONA,
        start.voice ?? DEFAULT_VOICE,
        start.guardrails ?? DEFAULT_GUARDRAILS,
        start.flow ?? null,
        asCard(start.agentCard),
      ));
      setHydrated(true);
      // Allow autosave after paint.
      window.setTimeout(() => {
        skipAutosave.current = false;
      }, 0);
    }
  }, [versionsQuery.data, hydrated, cardQuery.data?.agentCard]);

  // Sync persona chip to closest preset (or Custom).
  useEffect(() => {
    const match = presets.find(
      (p) => JSON.stringify(p.traits) === JSON.stringify(persona.traits),
    );
    setActivePresetId(match?.id ?? "custom");
  }, [persona.traits, presets]);

  // Baseline for `dirty`: the live row if there is one, else the newest version
  // of any status — for a clone with only a draft, that draft is the right
  // thing to diff against.
  const published = useMemo(() => {
    return history.find((v) => v.status === "published") ?? history[0];
  }, [history]);

  // The actually-published row, or nothing. The header used `published` and so
  // called a never-published clone's draft "published".
  const publishedRow = useMemo(
    () => history.find((v) => v.status === "published") ?? null,
    [history],
  );

  // What the tabs render and what every save sends. Local edits win; otherwise
  // the server's resolved card (draft-aware), then the version's own card.
  // A plain `??` chain was wrong here — the server returns `{}` for a card-less
  // bot, and `{} ?? x` is `{}`, so every cloned agent showed empty tabs.
  const effectiveCard = useMemo<AgentCard>(
    () =>
      card ??
      asCard(cardQuery.data?.agentCard) ??
      asCard(published?.agentCard) ??
      {},
    [card, cardQuery.data?.agentCard, published],
  );

  // Canary settings are a card field, not editor-local state. Keeping them
  // separate meant they never marked the editor dirty, never autosaved, and
  // were invisible to the compile preview — which read `card.experiment` and
  // cheerfully reported "full ship" for a publish that then 422'd at 40%.
  // A card-less bot has nowhere to put them, so it falls back to local state.
  const cardIsAuthored = Boolean(
    (effectiveCard as { identity?: { bot_id?: string } }).identity?.bot_id,
  );
  const ship = useMemo<ShipState>(() => {
    if (!cardIsAuthored) return legacyShip;
    const exp = (effectiveCard as {
      experiment?: { traffic_pct?: number; shadow?: boolean; auto_rollback?: string[] };
    }).experiment;
    return {
      trafficPct: typeof exp?.traffic_pct === "number" ? exp.traffic_pct : 100,
      shadow: Boolean(exp?.shadow),
      autoRollback: Array.isArray(exp?.auto_rollback) ? exp.auto_rollback : [],
    };
  }, [cardIsAuthored, effectiveCard, legacyShip]);

  const setShip = (next: ShipState) => {
    if (!cardIsAuthored) {
      setLegacyShip(next);
      return;
    }
    setCard({
      ...effectiveCard,
      experiment: {
        traffic_pct: next.trafficPct,
        shadow: next.shadow,
        auto_rollback: next.autoRollback,
      },
    });
  };

  const dirty = useMemo(() => {
    // No version to compare against: anything authored is a change. Returning
    // false here is what silently disabled autosave on a brand-new bot.
    if (!published) return hydrated && Boolean(prompt.trim());
    return (
      fingerprint(prompt, persona, voice, guardrails, flow, asCard(effectiveCard)) !==
      fingerprint(
        published.prompt,
        published.persona ?? DEFAULT_PERSONA,
        published.voice ?? DEFAULT_VOICE,
        published.guardrails ?? DEFAULT_GUARDRAILS,
        published.flow ?? null,
        asCard(cardQuery.data?.publishedCard) ?? asCard(published.agentCard),
      )
    );
    // `flow` belongs here: without it a canvas edit never recomputes `dirty`,
    // so the debounced autosave never fires and the graph is lost on navigate.
    // `effectiveCard` for the same reason — a Skills/Tools toggle is an edit.
  }, [
    prompt,
    persona,
    voice,
    guardrails,
    flow,
    effectiveCard,
    published,
    hydrated,
    cardQuery.data?.publishedCard,
  ]);

  // "Unsaved" is not "differs from what is live". On a card that has already
  // shipped, a saved draft differs from the published row for as long as it
  // exists — so the header's chip read "unsaved · draft v1.1" for the whole
  // session, including the instant after an autosave landed, and "Draft saved"
  // could never appear. This compares against what was last written instead.
  const unsaved = useMemo(
    () =>
      hydrated &&
      fingerprint(prompt, persona, voice, guardrails, flow, asCard(effectiveCard)) !==
        lastSavedFp.current,
    // savedTick is the dependency that makes reading the ref safe: it changes
    // whenever markSaved moves the baseline.
    [prompt, persona, voice, guardrails, flow, effectiveCard, hydrated, savedTick],
  );

  // Derived from the live row, not `published` — for a clone that fell through
  // to the draft's own label, and `nextVersionLabel("Collections-clone v1")`
  // does not match /^v\d+\.\d+$/, so it silently produced "v1.0".
  const nextLabel = nextVersionLabel(publishedRow?.label ?? "v1.0");

  // A draft keeps the name it was created with; `nextLabel` only names a new
  // one. Autosave used to PATCH `label: nextLabel` onto the existing draft, so
  // the first keystroke renamed "Collections-clone v1" to "v1.0".
  const draftLabel = useMemo(
    () => history.find((v) => v.id === draftId)?.label || nextLabel,
    [history, draftId, nextLabel],
  );
  const clearLint = useCallback(() => {
    setLintFindings([]);
    setLintedFp(null);
  }, []);

  const lintFp = useMemo(
    () => JSON.stringify({ prompt, guardrails }),
    [prompt, guardrails],
  );
  const freshLint = lintedFp === lintFp ? lintFindings : [];

  const personaLabel =
    activePresetId === "custom"
      ? "Custom persona"
      : (presets.find((p) => p.id === activePresetId)?.label ?? "Custom persona");
  const busy =
    publishMutation.isPending ||
    restoreMutation.isPending ||
    ensureDraftMutation.isPending ||
    discardMutation.isPending ||
    rollbackMutation.isPending;

  // Debounced autosave while dirty.
  useEffect(() => {
    if (!hydrated || skipAutosave.current) return;
    if (!dirty) {
      // "saved" survives here. The refetch that follows an autosave makes the
      // draft the newest version, so `dirty` goes false on the very next render
      // and this line reset the status to "idle" — wiping the "Draft saved"
      // confirmation before it could paint. The only feedback a successful save
      // gave was the *disappearance* of the unsaved chip. It clears on the next
      // edit, when the unsaved chip takes over.
      setSaveStatus((s) => (s === "saving" || s === "saved" ? s : "idle"));
      return;
    }
    const fp = fingerprint(prompt, persona, voice, guardrails, flow, asCard(effectiveCard));
    if (fp === lastSavedFp.current) return;

    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    autosaveTimer.current = window.setTimeout(() => {
      void (async () => {
        if (savingRef.current) {
          // Queue behind the save already running rather than racing it.
          resaveRef.current = true;
          return;
        }
        savingRef.current = true;
        setSaveStatus("saving");
        try {
          const draft = await ensureDraft({
            draftId,
            label: draftLabel,
            prompt,
            persona,
            voice,
            guardrails,
            flow: flow ?? undefined,
            agentCard: asCard(effectiveCard) ?? undefined,
            summary: "draft autosave",
            botId,
          });
          setDraftId(draft.id);
          markSaved(fingerprint(
            draft.prompt,
            draft.persona,
            draft.voice,
            draft.guardrails,
            draft.flow ?? null,
            asCard(draft.agentCard),
          ));
          setSaveStatus("saved");
        } catch {
          setSaveStatus("error");
        } finally {
          savingRef.current = false;
          if (resaveRef.current) {
            resaveRef.current = false;
            // Re-enter the effect so the edits made mid-save are written too.
            setAutosaveNonce((n) => n + 1);
          }
        }
      })();
    }, 1200);

    return () => {
      if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    };
    // `ensureDraft` rather than the whole mutation object: `useMutation`
    // returns a fresh object on every render, so depending on it restarted the
    // 1200ms debounce on every unrelated re-render — with a chatty neighbour on
    // the page (the Flow tab used to revalidate twice a second) the timer could
    // be pushed back indefinitely and nothing was ever saved.
  }, [
    prompt,
    persona,
    voice,
    guardrails,
    flow,
    effectiveCard,
    dirty,
    hydrated,
    draftId,
    draftLabel,
    botId,
    autosaveNonce,
    ensureDraft,
    markSaved,
  ]);

  // Compiler preview: same validator that publish uses. Runs even if the Flow
  // tab has never been opened, so a stored invalid graph cannot ship by
  // staying on the Prompt tab.
  useEffect(() => {
    if (isEmptyGraph(flow)) {
      setFlowValid(true);
      setFlowIssues([]);
      return;
    }
    // The canvas runs the same validator on the same graph, so while the Flow
    // tab is open this would double every request for an identical answer.
    // It is the mounted canvas that owns the result then; this exists for the
    // graph you never look at.
    if (tab === "flow") return;
    const timer = window.setTimeout(() => {
      void validateFlow(flow as FlowGraph)
        .then((result) => {
          setFlowValid(result.ok);
          setFlowIssues(result.issues);
        })
        .catch(() => {
          /* transient: keep the last known result */
        });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [flow, tab]);

  // Stable, and a no-op when nothing actually changed.
  //
  // The canvas reports validation, which lands in state, which re-renders this
  // component. An inline arrow here meant a new callback identity on every one
  // of those renders — and the canvas depended on that identity to schedule the
  // next validation. The two fed each other: POST /flow/validate roughly twice
  // a second for as long as the Flow tab was open. Fixed on both sides, because
  // one side alone is a coincidence rather than an invariant.
  const onFlowValidation = useCallback((r: { ok: boolean; issues: FlowIssue[] }) => {
    setFlowValid(r.ok);
    setFlowIssues((prev) =>
      prev.length === r.issues.length &&
      prev.every((issue, i) => {
        const next = r.issues[i];
        return (
          issue.code === next.code &&
          issue.severity === next.severity &&
          issue.nodeId === next.nodeId &&
          issue.edgeId === next.edgeId &&
          issue.message === next.message
        );
      })
        ? prev
        : r.issues,
    );
  }, []);

  const applyPreset = (p: PersonaPreset) => {
    // A preset replaces the whole prompt. Unannounced, that reads as data loss:
    // a click on the wrong card discards everything typed since the last
    // publish, with no undo and no warning. Ask first when there is work to
    // lose, and keep the previous text so the toast can put it back.
    const previous = prompt;
    const hasWork = Boolean(previous.trim()) && previous !== p.promptTemplate;
    if (
      hasWork &&
      !window.confirm(
        `Replace the whole system prompt with the "${p.label}" template?\n\n` +
          "Your current prompt text is discarded. Persona sliders move too.",
      )
    ) {
      return;
    }
    setPrompt(p.promptTemplate);
    setPersona((s) => ({ ...s, traits: p.traits }));
    setActivePresetId(p.id);
    clearLint();
    if (hasWork) {
      toast.success(`Applied preset: ${p.label}`, {
        action: { label: "Undo", onClick: () => setPrompt(previous) },
      });
    } else {
      toast.success(`Applied preset: ${p.label}`);
    }
  };

  const loadDraft = (v: PromptVersion) => {
    skipAutosave.current = true;
    setDraftId(v.id);
    setPrompt(v.prompt);
    setPersona(v.persona);
    setVoice(v.voice);
    setGuardrails(v.guardrails);
    setFlow(v.flow ?? null);
    setCard(asCard(v.agentCard));
    markSaved(fingerprint(
      v.prompt,
      v.persona,
      v.voice,
      v.guardrails,
      v.flow ?? null,
      asCard(v.agentCard),
    ));
    clearLint();
    setSaveStatus("saved");
    window.setTimeout(() => {
      skipAutosave.current = false;
    }, 0);
    toast.info(`Loaded draft ${v.label || v.id}`);
  };

  const discardDraft = async (v: PromptVersion) => {
    try {
      await discardMutation.mutateAsync(v.id);
      if (draftId === v.id) {
        const live = published;
        if (live) {
          skipAutosave.current = true;
          setDraftId(null);
          setPrompt(live.prompt);
          setPersona(live.persona);
          setVoice(live.voice);
          setGuardrails(live.guardrails);
          setFlow(live.flow ?? null);
          setCard(asCard(live.agentCard));
          markSaved(fingerprint(
            live.prompt,
            live.persona,
            live.voice,
            live.guardrails,
            live.flow ?? null,
            asCard(live.agentCard),
          ));
          setSaveStatus("idle");
          window.setTimeout(() => {
            skipAutosave.current = false;
          }, 0);
        }
      }
      toast.success(`Discarded draft ${v.label || v.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Discard failed");
    }
  };

  const restore = async (v: PromptVersion) => {
    try {
      const draft = await restoreMutation.mutateAsync(v.id);
      loadDraft(draft);
      toast.info(`Restored ${v.label} into draft — publish to make it live.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Restore failed");
    }
  };

  const publish = async (note: string) => {
    if (!flowValid) {
      toast.error("Fix conversation-flow errors before publishing.");
      setTab("flow");
      return;
    }
    try {
      const publishedRow = await publishMutation.mutateAsync({
        draftId,
        label: draftLabel,
        prompt,
        persona,
        voice,
        guardrails,
        summary: note,
        flow: flow ?? undefined,
        agentCard: asCard(effectiveCard) ?? undefined,
        botId,
        trafficPct: ship.trafficPct,
        shadow: ship.shadow,
        autoRollback: ship.autoRollback,
      });
      skipAutosave.current = true;
      setDraftId(null);
      setPublishOpen(false);
      setPrompt(publishedRow.prompt);
      setPersona(publishedRow.persona);
      setVoice(publishedRow.voice);
      setGuardrails(publishedRow.guardrails);
      setFlow(publishedRow.flow ?? null);
      setCard(asCard(publishedRow.agentCard));
      markSaved(fingerprint(
        publishedRow.prompt,
        publishedRow.persona,
        publishedRow.voice,
        publishedRow.guardrails,
        publishedRow.flow ?? null,
        asCard(publishedRow.agentCard),
      ));
      setSaveStatus("idle");
      clearLint();
      window.setTimeout(() => {
        skipAutosave.current = false;
      }, 0);
      toast.success(`Published ${publishedRow.label || nextLabel}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Publish failed");
    }
  };

  const onRollback = async () => {
    const targetId = activeDeployment?.rollbackDeploymentId ?? priorDeployment?.id;
    if (!targetId) {
      toast.info("No prior production deployment to roll back to.");
      return;
    }
    try {
      const dep = await rollbackMutation.mutateAsync(targetId);
      const live = (await versionsQuery.refetch()).data?.find((v) => v.id === dep.promptVersionId);
      if (live) {
        skipAutosave.current = true;
        setDraftId(null);
        setPrompt(live.prompt);
        setPersona(live.persona);
        setVoice(live.voice);
        setGuardrails(live.guardrails);
        setFlow(live.flow ?? null);
        setCard(asCard(live.agentCard));
        markSaved(fingerprint(
          live.prompt,
          live.persona,
          live.voice,
          live.guardrails,
          live.flow ?? null,
          asCard(live.agentCard),
        ));
        window.setTimeout(() => {
          skipAutosave.current = false;
        }, 0);
      }
      toast.success(`Rolled back live config to ${dep.promptVersionId}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Rollback failed");
    }
  };

  const onLint = async () => {
    try {
      const findings = await lintMutation.mutateAsync({ prompt, guardrails });
      setLintFindings(findings);
      setLintedFp(JSON.stringify({ prompt, guardrails }));
      // Only leave the current tab when there is something to look at, and
      // never for warnings alone. Jumping unconditionally yanked you out of the
      // Flow canvas mid-edit to show a panel saying everything was fine.
      if (findings.some((f) => f.severity === "error")) setTab("prompt");
      if (!findings.length) toast.success("Lint clean — no issues found");
      else {
        const errors = findings.filter((f) => f.severity === "error").length;
        // CRM-variable findings are rendered by the editor's own always-on
        // banner, not the findings list, so a lint that produced only those
        // would announce "4 findings" and then appear to show nothing new.
        const inlineOnly = findings.every(
          (f) => f.code === "crm_variable_in_system_prompt",
        );
        toast.message(`Lint: ${findings.length} finding(s)`, {
          description: errors
            ? `${errors} error(s) to review before publish`
            : inlineOnly
              ? "All about CRM variables — flagged inline under the editor"
              : "Warnings only — open the System Prompt tab to read them",
          // Warnings leave you where you are, so the toast has to offer the way
          // there rather than assume you were on the prompt already.
          action: errors ? undefined : { label: "Review", onClick: () => setTab("prompt") },
        });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lint failed");
    }
  };

  const onTestSandbox = async () => {
    try {
      let versionId = published?.id;
      if (dirty) {
        const draft = await ensureDraftMutation.mutateAsync({
          draftId,
          label: draftLabel,
          prompt,
          persona,
          voice,
          guardrails,
          flow: flow ?? undefined,
          agentCard: asCard(effectiveCard) ?? undefined,
          summary: "sandbox try",
          botId,
        });
        setDraftId(draft.id);
        markSaved(fingerprint(
          draft.prompt,
          draft.persona,
          draft.voice,
          draft.guardrails,
          draft.flow ?? null,
          asCard(draft.agentCard),
        ));
        versionId = draft.id;
      }
      if (!versionId) {
        toast.info("No version to test yet.");
        return;
      }
      void navigate({
        to: "/sandbox",
        // botId matters: the sandbox lists versions for the bot it has selected,
        // which defaults to kaia-v2-4. Without it, a draft belonging to any
        // other card was not found and the page quietly rehearsed kaia's
        // published version instead — a green sandbox run for the wrong agent.
        search: { promptVersionId: versionId, botId },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not prepare sandbox draft");
    }
  };

  const TABS: Array<{ key: Tab; label: string; icon: typeof FileText }> = [
    { key: "prompt", label: "System Prompt", icon: FileText },
    { key: "flow", label: "Flow", icon: Workflow },
    { key: "graph", label: "Agent graph", icon: GitBranch },
    { key: "persona", label: "Persona", icon: Sparkles },
    { key: "voice", label: "Voice (TTS)", icon: Volume2 },
    { key: "guardrails", label: "Guardrails", icon: ShieldAlert },
    { key: "tools", label: "Tools", icon: Wrench },
    { key: "skills", label: "Skills", icon: Layers },
    { key: "connectors", label: "Connectors", icon: Plug },
    { key: "policy", label: "Policy", icon: Lock },
    { key: "evals", label: "Evals", icon: FlaskConical },
    { key: "ship", label: "Ship", icon: Rocket },
  ];

  // What a publish is measured against: the live row, and nothing else.
  //
  // This used to read `published`, which falls back to the newest version of
  // any status — on a card that has never shipped, that is the very draft being
  // published. The dialog diffed the draft against itself and reported
  // "+0 · -0 lines" for a publish that introduced the entire prompt.
  const publishBaseline = useMemo(
    () => ({
      prompt: publishedRow?.prompt ?? "",
      persona: publishedRow?.persona ?? DEFAULT_PERSONA,
      voice: publishedRow?.voice ?? DEFAULT_VOICE,
      guardrails: publishedRow?.guardrails ?? DEFAULT_GUARDRAILS,
    }),
    [publishedRow],
  );

  const loading = versionsQuery.isLoading && !hydrated;
  const currentSnapshot = {
    label: dirty ? `${draftLabel} (draft)` : published?.label ?? "draft",
    prompt,
    persona,
    voice,
    guardrails,
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <StudioHeader
          cardName={cardQuery.data?.name}
          currentVersion={publishedRow?.label ?? "—"}
          canPublish={Boolean(draftId) || dirty}
          nextVersion={draftLabel}
          dirty={unsaved}
          personaLabel={personaLabel}
          saveStatus={saveStatus}
          onTestSandbox={() => void onTestSandbox()}
          onPublish={() => {
            setPublishOpen(true);
            // Never show the last run's gates for this one.
            setCompileReport(null);
            void compileMutation
              .mutateAsync({
                flow: flow ?? undefined,
                agentCard: asCard(effectiveCard) ?? undefined,
                // What Confirm will actually send. Omitting these made the
                // dialog preview a different publish than the one it runs.
                trafficPct: ship.trafficPct,
                autoRollback: ship.autoRollback,
              })
              .then((report) => setCompileReport(report))
              .catch(() => setCompileReport(null));
          }}
          onLint={() => void onLint()}
          lintBusy={lintMutation.isPending}
          publishBlocked={!flowValid}
          flowErrorCount={flowIssues.filter((i) => i.severity === "error").length}
          onFixFlow={() => setTab("flow")}
        />

        {showGapBanner && (
          <div className="mx-250 mt-150 flex items-start justify-between gap-150 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
            <div>
              <div className="font-semibold text-text-warning-bolder">Fixing unanswered question</div>
              <div className="mt-025 text-text-warning-bolder/90">
                {gapNote || "Review the system prompt for this coverage gap."}
                {unansweredId ? (
                  <span className="ml-050 font-mono text-body-small text-text-warning-bolder/70">({unansweredId})</span>
                ) : null}
              </div>
              <div className="mt-050 text-body-small text-text-warning-bolder/80">
                Banner only — edit the prompt yourself; nothing is auto-injected.
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                setGapBannerDismissed(true);
                void navigate({ to: "/agent-studio/$botId", params: { botId }, search: {} });
              }}
              className="shrink-0 rounded border border-border-warning px-100 py-025 text-body-small hover:bg-background-warning-subtler"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* The twelve tabs need 1006px and the strip had `overflow-x: visible`
            and no scrolling, so below roughly 1030px the last of them simply
            hung outside the container with nothing to reach them by: on a
            1024px laptop, or this app in a split window, Evals and Ship were
            unclickable — including the only route to canary and publish
            settings. Scrolling the strip is the fix; `shrink-0` stops the
            labels compressing into ellipses instead. */}
        <div
          ref={tabStripRef}
          className="shrink-0 overflow-x-auto border-b border-border bg-surface px-250"
        >
          <div className="flex w-max gap-050">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.key}
                  data-tab={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-075 border-b-2 px-150 py-100 text-body-small",
                    tab === t.key
                      ? "border-border-brand font-semibold text-text-brand"
                      : "border-transparent text-text-subtle hover:text-text",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>

        {loading ? (
          <div className="grid flex-1 place-items-center p-250">
            <LoadingState label="Loading prompt studio" />
          </div>
        ) : versionsQuery.isError ? (
          <div className="p-250 text-body text-text-danger-bolder">
            Failed to load prompt versions. Check the API / mock toggle.
          </div>
        ) : (
          <div
            className={cn(
              "grid min-h-0 flex-1 grid-cols-1",
              // The Flow tab needs every pixel: the canvas already competes
              // with its own node inspector, and version history is
              // prompt-version chrome that says nothing about a graph.
              tab === "flow" ? "xl:grid-cols-1" : "xl:grid-cols-[1fr_320px]",
            )}
          >
            <div
              className={cn(
                "min-h-0 p-250",
                // Fixed 36rem wasted ~400px below the canvas on a 1080p screen.
                tab === "flow" ? "overflow-hidden" : "overflow-y-auto",
              )}
            >
              {tab === "graph" && (
                <AgentGraphTab
                  botId={botId}
                  card={effectiveCard as never}
                  onChange={(next) => setCard(next as AgentCard)}
                />
              )}
              {tab === "tools" && (
                <ToolsTab
                  botId={botId}
                  card={effectiveCard as never}
                  onChange={(next) => setCard(next as AgentCard)}
                />
              )}
              {tab === "skills" && (
                <SkillsTab
                  card={effectiveCard as never}
                  onChange={(next) => setCard(next as AgentCard)}
                />
              )}
              {tab === "connectors" && (
                <ConnectorsTab
                  card={effectiveCard as never}
                  onChange={(next) => setCard(next as AgentCard)}
                />
              )}
              {tab === "policy" && <PolicyTab card={effectiveCard as never} />}
              {tab === "evals" && <EvalsTab botId={botId} card={effectiveCard as never} />}
              {tab === "ship" && (
                <ShipTab
                  botId={botId}
                  value={ship}
                  onChange={setShip}
                  activeDeploymentId={activeDeployment?.id}
                />
              )}
              {tab === "prompt" && (
                <PromptEditor
                  value={prompt}
                  onChange={setPrompt}
                  onApplyPreset={applyPreset}
                  presets={presets}
                  lintFindings={freshLint}
                  onClearLint={clearLint}
                />
              )}
              {tab === "persona" && (
                <PersonaSliders
                  value={persona}
                  onChange={setPersona}
                  presets={presets}
                  voice={voice}
                />
              )}
              {tab === "voice" && (
                <VoicePanel value={voice} onChange={setVoice} />
              )}
              {tab === "guardrails" && (
                <GuardrailsPanel value={guardrails} onChange={setGuardrails} />
              )}
              {tab === "flow" && (
                <div className="h-full min-h-0">
                  {isEmptyGraph(flow) ? (
                    // An empty flow is meaningful, not missing: the runtime reads
                    // it as "use the built-in collections script". Seeding a graph
                    // on load would silently change what this version does, so it
                    // takes an explicit action.
                    <div className="flex h-full flex-col items-center justify-center gap-150 rounded-medium border border-dashed border-border text-center">
                      <div className="max-w-lg space-y-075 px-200">
                        <h3 className="text-body font-semibold text-text">
                          No authored flow
                        </h3>
                        <p className="text-body-small leading-relaxed text-text-subtle">
                          This version runs the built-in collections script — Python
                          that publish and rollback cannot touch. Load it here to turn
                          it into a graph you own: it then publishes and rolls back
                          with this prompt version. Nothing changes for live callers
                          until you publish. Set{" "}
                          <code className="font-mono text-text-subtlest">
                            VOICE_FLOW_GRAPH=legacy
                          </code>{" "}
                          to force the built-in script even when a graph exists.
                        </p>
                      </div>
                      <div className="flex flex-wrap justify-center gap-100">
                        <Button
                          disabled={loadingBuiltIn}
                          onClick={() => {
                            setLoadingBuiltIn(true);
                            void fetchBuiltInFlow()
                              .then((g) => {
                                setFlow(g);
                                toast.success(
                                  `Loaded the built-in script — ${g.nodes.length} nodes. Publish to make it live.`,
                                );
                              })
                              .catch((err: unknown) =>
                                toast.error(
                                  err instanceof Error ? err.message : "Could not load the built-in flow",
                                ),
                              )
                              .finally(() => setLoadingBuiltIn(false));
                          }}
                        >
                          <Workflow className="mr-050 h-4 w-4" />
                          {loadingBuiltIn ? "Loading…" : "Load the built-in script"}
                        </Button>
                        <Button variant="outline" onClick={() => setFlow(emptyGraph())}>
                          Start from blank
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <FlowCanvas
                      graph={flow as FlowGraph}
                      onChange={setFlow}
                      onValidation={onFlowValidation}
                    />
                  )}
                </div>
              )}
            </div>
            <div className={cn("hidden min-h-0", tab === "flow" ? "" : "xl:block")}>
              <VersionHistory
                versions={history}
                activeDraftId={draftId}
                activeDeployment={activeDeployment}
                priorDeployment={priorDeployment}
                onCompare={(v) => {
                  setDiffBase(v);
                  setDiffOpen(true);
                }}
                onRestore={(v) => void restore(v)}
                onLoadDraft={loadDraft}
                onDiscardDraft={(v) => discardDraft(v)}
                onRollback={() => void onRollback()}
                rollbackBusy={rollbackMutation.isPending}
              />
            </div>
          </div>
        )}

        <DiffModal
          open={diffOpen}
          onOpenChange={setDiffOpen}
          base={diffBase}
          current={currentSnapshot}
        />

        <PublishDialog
          open={publishOpen}
          onOpenChange={setPublishOpen}
          fromLabel={publishedRow?.label ?? "nothing live"}
          toLabel={draftLabel}
          from={publishBaseline}
          to={{ prompt, persona, voice, guardrails }}
          flowIssues={flowIssues}
          compileReport={compileReport}
          compileBusy={compileMutation.isPending}
          onConfirm={(note) => void publish(note)}
        />

        {busy && (
          <div className="pointer-events-none fixed bottom-4 right-4 rounded-medium bg-background-brand-boldest/90 px-150 py-075 text-body-small text-white shadow-overlay">
            Saving…
          </div>
        )}
      </div>
    </AppShell>
  );
}
