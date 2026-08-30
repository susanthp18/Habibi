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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
  useAutoLint,
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
  languageTag,
  nextVersionLabel,
  type Guardrails,
  type PersonaPreset,
  type PersonaState,
  type PromptVersion,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import {
  FileText,
  Sparkles,
  Volume2,
  ShieldAlert,
  Workflow,
  Wrench,
  Lock,
  PhoneOutgoing,
  FlaskConical,
  GitBranch,
  Layers,
  Plug,
  Rocket,
  Cable,
  ScrollText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/ui/loading-state";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import {
  useAgentStudioCard,
  useCompileCard,
  useDeploymentExperiments,
  type CompileReport,
} from "@/api/agent-studio";
import { stableStringify } from "@/lib/stable-stringify";
import { isNotFound } from "@/api/config";
import { asRollbackTriggers, isAuthoredCard, type AgentCard } from "@/api/agent-card";
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
  | "outbound"
  | "bindings"
  | "evals"
  | "ship"
  | "changelog";
/**
 * Tabs that own their own height and scroll internally, rather than growing a
 * page that scrolls.
 *
 * The distinction is real, not cosmetic. Flow is a canvas and Voice is a
 * browser-plus-inspector: both have a natural size of "the pane", and both
 * contain their own scrollable regions. Letting the page scroll underneath
 * them means two scrollbars competing for the same wheel gesture. The rest are
 * forms — they have a natural height, and the page should scroll them.
 */
const FILL_TABS = new Set<Tab>(["flow", "voice"]);

type SaveStatus = "idle" | "saving" | "saved" | "error";

/** Non-empty object, or null. `{}` is "no card", not "a card with no fields". */
function asCard(value: unknown): AgentCard | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.keys(value as AgentCard).length ? (value as AgentCard) : null;
}

/**
 * Identity of the editor's state, used for both "is this dirty?" and "has this
 * already been autosaved?".
 *
 * `stableStringify`, not `JSON.stringify`, and the difference is the whole
 * bug. Key order matters to JSON.stringify and the two sides of this comparison
 * are built differently: local state starts from `DEFAULT_VOICE`, which omits
 * `style` and `params`, while the server emits every field in Pydantic field
 * order. So the first save stored a server-shaped baseline against seed-shaped
 * local state, `dirty` recomputed true the instant "Draft saved" appeared, and
 * the save invalidated the query that refetched the object that re-ran the
 * effect. A permanent unsaved chip on top of a PATCH loop that feeds itself.
 *
 * PublishDialog had already hit this and grown its own key-order-independent
 * serialiser; it now lives in @/lib/stable-stringify and both use it.
 */
function fingerprint(
  p: string,
  persona: PersonaState,
  voice: VoiceConfig,
  g: Guardrails,
  flow: FlowGraph | null,
  card: AgentCard | null,
) {
  return stableStringify({ p, persona, voice, g, flow, card });
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
  const experimentsQuery = useDeploymentExperiments(botId);
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
  // Preset awaiting confirmation because applying it would discard authored text.
  const [presetPending, setPresetPending] = useState<PersonaPreset | null>(null);
  // The dialog animates out over ~150ms, and it reads its subject from
  // `presetPending` — which is already null by then, so the sentence degraded to
  // "Applying  overwrites the prompt…" on the way out. Hold the last subject so
  // the closing frame says the same thing the open one did.
  const presetShown = useRef<PersonaPreset | null>(null);
  if (presetPending) presetShown.current = presetPending;
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [diffBase, setDiffBase] = useState<PromptVersion | undefined>();
  const [publishOpen, setPublishOpen] = useState(false);
  const [compileReport, setCompileReport] = useState<CompileReport | null>(null);
  /** Why the last compile produced no report. See `runCompile`. */
  const [compileError, setCompileError] = useState<string | null>(null);
  // Ship settings for a bot with no Agent Card. An authored card keeps them in
  // `card.experiment` instead — see `ship` below.
  //
  // `null` until the live experiment has been read, deliberately. This state is
  // not persisted anywhere, so seeding it with hardcoded 100/false/[] meant the
  // Ship tab asserted "full ship, no shadow, no auto-rollback" for a bot that
  // might be running a 25% shadow canary — and asserted it again after every
  // reload, silently discarding whatever the operator set last time. Falling
  // back to what production is actually running is the only defensible resting
  // value; `legacyShipBaseline` below is that value, and doubles as the diff
  // baseline the publish dialog was missing.
  const [legacyShipEdit, setLegacyShipEdit] = useState<ShipState | null>(null);

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
  // Which edges of the tab strip still have tabs hidden behind them. The strip
  // scrolls, but a bare scrollbar under a tab row reads as breakage rather than
  // as an affordance — and at 1024px it was the only clue that Evals and Ship
  // existed at all. A fade on the side that has more is the honest signal.
  const [tabEdges, setTabEdges] = useState({ atStart: true, atEnd: true });
  const syncTabEdges = useCallback(() => {
    const el = tabStripRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setTabEdges({
      atStart: el.scrollLeft <= 1,
      // 1px of slack: sub-pixel layout widths leave scrollLeft a hair short of
      // max even when it is visually at the end, which would pin the fade on.
      atEnd: el.scrollLeft >= max - 1,
    });
  }, []);

  useEffect(() => {
    tabStripRef.current
      ?.querySelector<HTMLElement>(`[data-tab="${tab}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
    syncTabEdges();
  }, [tab, syncTabEdges]);

  useEffect(() => {
    const el = tabStripRef.current;
    if (!el) return;
    syncTabEdges();
    const ro = new ResizeObserver(syncTabEdges);
    ro.observe(el);
    return () => ro.disconnect();
  }, [syncTabEdges]);

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
  /**
   * The summary autosave writes onto the open draft.
   *
   * A ref rather than state because nothing renders it and changing it must not
   * re-run the autosave effect. It exists so that a draft created by
   * restore-as-draft keeps its "restored from vX" note: autosave used to send a
   * literal "draft autosave" on every write, so the note lasted one keystroke.
   */
  const draftSummary = useRef("draft autosave");
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
    // Newest first, explicitly. `rows.find(...)` took whatever the API happened
    // to return first, and "roll back to a deployment picked by list order" is
    // not a thing anyone can reason about — the one guarantee a rollback owes
    // its operator is that it goes back exactly one step.
    return (
      rows
        .filter((d) => d.status === "retired" || d.status === "rolled_back")
        .slice()
        .sort((a, b) => (b.publishedAt ?? "").localeCompare(a.publishedAt ?? ""))[0] ?? null
    );
  }, [prodDepsQuery.data, activeDeployment]);

  // Hydrate editor from published once; keep history in sync with query refetches.
  useEffect(() => {
    if (!versionsQuery.data) return;
    // Not before the card read has settled. `/prompt-versions` answers `200 []`
    // for any id at all, so hydration would otherwise complete — and the editor
    // render with it — while the question "does this bot exist?" was still in
    // flight. On a dead URL that produced a fully editable studio during the
    // gap, and autosave was pointed at it.
    if (cardQuery.isPending) return;
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
      draftSummary.current = newestDraft?.summary || "draft autosave";
      markSaved(
        fingerprint(
          start.prompt,
          start.persona ?? DEFAULT_PERSONA,
          start.voice ?? DEFAULT_VOICE,
          start.guardrails ?? DEFAULT_GUARDRAILS,
          start.flow ?? null,
          asCard(start.agentCard),
        ),
      );
      setHydrated(true);
      // Allow autosave after paint.
      window.setTimeout(() => {
        skipAutosave.current = false;
      }, 0);
    }
  }, [versionsQuery.data, hydrated, cardQuery.data?.agentCard, cardQuery.isPending]);

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
    () => card ?? asCard(cardQuery.data?.agentCard) ?? asCard(published?.agentCard) ?? {},
    [card, cardQuery.data?.agentCard, published],
  );

  // Canary settings are a card field, not editor-local state. Keeping them
  // separate meant they never marked the editor dirty, never autosaved, and
  // were invisible to the compile preview — which read `card.experiment` and
  // cheerfully reported "full ship" for a publish that then 422'd at 40%.
  // A card-less bot has nowhere to put them, so it falls back to local state.
  const cardIsAuthored = isAuthoredCard(effectiveCard);

  /**
   * What production is running, for a bot that has nowhere to author it.
   *
   * The live experiment row is the only durable record of a card-less bot's
   * rollout, so it is both the resting value of the Ship tab's controls and the
   * baseline the publish dialog diffs against. Absent one, a bot with an active
   * deployment is at full traffic by definition, which is what the API means by
   * having no experiment at all.
   */
  const legacyShipBaseline = useMemo<ShipState>(() => {
    const live = (experimentsQuery.data ?? []).find((e) => e.status === "active");
    if (!live) return { trafficPct: 100, shadow: false, autoRollback: [] };
    return {
      trafficPct: live.trafficPct,
      shadow: live.shadow,
      autoRollback: asRollbackTriggers(live.autoRollback),
    };
  }, [experimentsQuery.data]);
  const ship = useMemo<ShipState>(() => {
    if (!cardIsAuthored) return legacyShipEdit ?? legacyShipBaseline;
    const exp = effectiveCard.experiment;
    return {
      trafficPct: typeof exp?.traffic_pct === "number" ? exp.traffic_pct : 100,
      shadow: Boolean(exp?.shadow),
      autoRollback: asRollbackTriggers(exp?.auto_rollback),
    };
  }, [cardIsAuthored, effectiveCard, legacyShipEdit, legacyShipBaseline]);

  const setShip = (next: ShipState) => {
    if (!cardIsAuthored) {
      setLegacyShipEdit(next);
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

  const lintFp = useMemo(() => JSON.stringify({ prompt, guardrails }), [prompt, guardrails]);
  // The deterministic pass, running continuously. It used to need a button, and
  // the cost of that showed up in the data: three PUBLISHED cards carry CRM
  // tokens that delete the line they sit on, including the one every inbound
  // call resolves to. Nobody had pressed it.
  const autoLint = useAutoLint({ prompt, guardrails });
  // The Critique pass still answers on demand, and its rows are additive: the
  // auto pass never returns llm_checklist, so the two cannot double up.
  //
  // The advisory filter lives inside the memo rather than beside it because a
  // fresh array on every render is a dependency that changes on every render —
  // the memo would recompute always and memoise nothing. `lintedFp === lintFp`
  // is the staleness guard: advice is dropped the moment the prompt or the
  // guardrails move away from what was actually critiqued.
  const freshLint = useMemo(() => {
    const advisory =
      lintedFp === lintFp ? lintFindings.filter((f) => f.code === "llm_checklist") : [];
    return [...(autoLint.data ?? []), ...advisory];
  }, [autoLint.data, lintFindings, lintedFp, lintFp]);

  // Derived, not stored. Two bugs lived in the stored version: it was set from
  // the traits alone, so rewriting the prompt into something unrecognisable
  // left the badge still naming the preset ("Empathetic Collector" above text
  // that was nothing of the sort); and `applyPreset`'s own
  // `setActivePresetId(p.id)` was dead code, overwritten by the trait-sync
  // effect on the same render.
  //
  // A preset applies BOTH a prompt and a set of traits, so it is only still in
  // effect while both match. Deriving it means there is no second copy of the
  // answer to keep in step — with the effect gone, loading a draft, undoing a
  // preset and hydrating from the server are all correct for free, and each was
  // a path that left the badge stale before.
  const personaLabel = useMemo(() => {
    const match = presets.find(
      (p) =>
        p.promptTemplate.trim() === prompt.trim() &&
        JSON.stringify(p.traits) === JSON.stringify(persona.traits),
    );
    return match?.label ?? "Custom persona";
  }, [presets, prompt, persona.traits]);

  // Every language the card claims, as BCP-47. Primary first — the Voice tab
  // opens its catalog filter there — then the vernacular fallbacks, which are
  // languages this card is authored to speak and so cannot be a locale
  // mismatch. `languageTag` returns undefined for a name this build has no tag
  // for, and an empty set makes the guard stand down rather than guess.
  const cardLocales = useMemo(
    () =>
      [persona.language, ...(persona.fallbackLanguages ?? [])]
        .map((name) => languageTag(name))
        .filter((tag): tag is string => Boolean(tag)),
    [persona.language, persona.fallbackLanguages],
  );
  const busy =
    publishMutation.isPending ||
    restoreMutation.isPending ||
    ensureDraftMutation.isPending ||
    discardMutation.isPending ||
    rollbackMutation.isPending;

  // Debounced autosave while dirty.
  useEffect(() => {
    if (!hydrated || skipAutosave.current) return;
    // Never autosave against a card the API could not confirm exists. On a dead
    // URL `/prompt-versions` still answers `200 []`, so hydration succeeds and
    // every keystroke used to PATCH a bot id nothing is registered under.
    if (cardQuery.isError) return;
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
            summary: draftSummary.current,
            botId,
          });
          setDraftId(draft.id);
          markSaved(
            fingerprint(
              draft.prompt,
              draft.persona,
              draft.voice,
              draft.guardrails,
              draft.flow ?? null,
              asCard(draft.agentCard),
            ),
          );
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
    cardQuery.isError,
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

  // Commit a preset. Split from the click handler so the confirmation step can
  // sit between them without the write path knowing a dialog exists.
  const commitPreset = useCallback(
    (p: PersonaPreset) => {
      // Both halves of what a preset writes, and always an Undo.
      //
      // It restored the prompt only, so the traits it moved in the same click —
      // 75/40/55/60/20 to 35/80/65/40/15 — had no way back short of
      // remembering five numbers. And the Undo was conditional on the prompt
      // having changed, so applying a preset whose template was already in the
      // editor offered nothing at all while the sliders still jumped.
      const previousPrompt = prompt;
      const previousTraits = persona.traits;
      setPrompt(p.promptTemplate);
      setPersona((s) => ({ ...s, traits: p.traits }));
      clearLint();
      toast.success(`Applied ${p.label}`, {
        action: {
          label: "Undo",
          onClick: () => {
            setPrompt(previousPrompt);
            setPersona((s) => ({ ...s, traits: previousTraits }));
            clearLint();
          },
        },
      });
    },
    [prompt, persona.traits, clearLint],
  );

  // One compile, two callers. The Publish button ran it inline; the Ship tab
  // said "run Compile" and offered nothing to run, so the one screen named
  // after shipping was the one place you could not ask whether the card would.
  // Sharing the call is what keeps the two reports describing the same publish.
  const runCompile = useCallback(() => {
    // Never show the last run's gates for this one.
    setCompileReport(null);
    return compileMutation
      .mutateAsync({
        flow: flow ?? undefined,
        agentCard: asCard(effectiveCard) ?? undefined,
        // What Confirm will actually send. Omitting these made the dialog
        // preview a different publish than the one it runs.
        trafficPct: ship.trafficPct,
        autoRollback: ship.autoRollback,
        // G15 reads the mouth columns, which live here unsaved between
        // autosaves. Without them the compiler gates the last save while
        // Publish ships what is on screen.
        voice,
        persona,
      })
      .then((report) => {
        setCompileError(null);
        setCompileReport(report);
      })
      .catch((err: unknown) => {
        // A compile that could not run is not a compile with nothing to say.
        // This used to swallow the error and leave `compileReport` null, which
        // the publish dialog renders as simply having no gate section — so the
        // evidence panel silently disappeared and the operator was left to
        // decide from a dialog that had stopped mentioning the compiler at all.
        setCompileReport(null);
        setCompileError(err instanceof Error ? err.message : "The compiler did not answer.");
      });
  }, [compileMutation, flow, effectiveCard, ship.trafficPct, ship.autoRollback, voice, persona]);

  const applyPreset = useCallback(
    (p: PersonaPreset) => {
      // A preset replaces the whole prompt. Unannounced, that reads as data
      // loss: a click on the wrong card discards everything typed since the
      // last publish. Ask first when there is work to lose — and ask in the
      // app's own dialog, not window.confirm, which paints as browser chrome
      // titled with the origin ("localhost:8080 says"), cannot be themed, and
      // blocks the renderer thread while it is open.
      const hasWork = Boolean(prompt.trim()) && prompt !== p.promptTemplate;
      if (hasWork) {
        setPresetPending(p);
        return;
      }
      commitPreset(p);
    },
    [prompt, commitPreset],
  );

  const loadDraft = (v: PromptVersion) => {
    skipAutosave.current = true;
    setDraftId(v.id);
    setPrompt(v.prompt);
    // `?? DEFAULT_*` here for the same reason the hydration path has it: these
    // three are non-null on every row served today, but a null would put
    // `undefined` into state that half a dozen tabs dereference without a guard,
    // and the crash would land on whichever tab the author opened next rather
    // than here.
    setPersona(v.persona ?? DEFAULT_PERSONA);
    setVoice(v.voice ?? DEFAULT_VOICE);
    setGuardrails(v.guardrails ?? DEFAULT_GUARDRAILS);
    setFlow(v.flow ?? null);
    setCard(asCard(v.agentCard));
    // Autosave writes this back on the next keystroke. Before it was tracked,
    // autosave sent a hardcoded "draft autosave" every time, so the note
    // restore-as-draft had just written ("restored from v1.2") survived exactly
    // until the author typed one character — and the version history then
    // described a restored draft as an ordinary autosave.
    draftSummary.current = v.summary || "draft autosave";
    markSaved(
      fingerprint(
        v.prompt,
        v.persona ?? DEFAULT_PERSONA,
        v.voice ?? DEFAULT_VOICE,
        v.guardrails ?? DEFAULT_GUARDRAILS,
        v.flow ?? null,
        asCard(v.agentCard),
      ),
    );
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
        // Explicitly not `published`. That falls back to `history[0]` when the
        // card has never shipped, and on a draft-only card `history[0]` can BE
        // the row just discarded — the refetch has not landed yet — so
        // discarding reloaded the discarded text straight back into the editor,
        // where autosave would have written it out again as a new draft.
        const live =
          history.find((h) => h.status === "published" && h.id !== v.id) ??
          history.find((h) => h.id !== v.id) ??
          null;
        if (live) {
          skipAutosave.current = true;
          setDraftId(null);
          setPrompt(live.prompt);
          setPersona(live.persona ?? DEFAULT_PERSONA);
          setVoice(live.voice ?? DEFAULT_VOICE);
          setGuardrails(live.guardrails ?? DEFAULT_GUARDRAILS);
          setFlow(live.flow ?? null);
          setCard(asCard(live.agentCard));
          draftSummary.current = "draft autosave";
          markSaved(
            fingerprint(
              live.prompt,
              live.persona ?? DEFAULT_PERSONA,
              live.voice ?? DEFAULT_VOICE,
              live.guardrails ?? DEFAULT_GUARDRAILS,
              live.flow ?? null,
              asCard(live.agentCard),
            ),
          );
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
      markSaved(
        fingerprint(
          publishedRow.prompt,
          publishedRow.persona,
          publishedRow.voice,
          publishedRow.guardrails,
          publishedRow.flow ?? null,
          asCard(publishedRow.agentCard),
        ),
      );
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
        markSaved(
          fingerprint(
            live.prompt,
            live.persona,
            live.voice,
            live.guardrails,
            live.flow ?? null,
            asCard(live.agentCard),
          ),
        );
        window.setTimeout(() => {
          skipAutosave.current = false;
        }, 0);
      }
      toast.success(`Rolled back live config to ${dep.promptVersionId}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Rollback failed");
    }
  };

  // The costed half, on demand. The free deterministic pass now runs itself
  // (`useAutoLint`), so this exists only to add the model's read of the WRITING
  // — vagueness, contradictions, promises no tool can keep. It is told the
  // guardrails are already enforced and will not report them as missing.
  //
  // Still a request for the whole lint with `includeLlm`, because the backend
  // owns that composition; only the advisory rows are kept from the response,
  // the deterministic ones being on screen already.
  const onLint = async (includeLlm = true) => {
    try {
      const findings = await lintMutation.mutateAsync({ prompt, guardrails, includeLlm });
      setLintFindings(findings);
      setLintedFp(JSON.stringify({ prompt, guardrails }));
      const advice = findings.filter((f) => f.code === "llm_checklist");
      const unavailable = findings.find(
        (f) => f.code === "llm_lint_failed" || f.code === "llm_lint_unavailable",
      );
      if (unavailable) {
        // A review that could not run must never read as a clean bill of health.
        toast.error("Critique unavailable", { description: unavailable.message });
      } else if (!advice.length) {
        toast.success("Critique clean — nothing flagged in the wording");
      } else {
        toast.message(`Critique: ${advice.length} suggestion(s)`, {
          description: "Advisory — listed beside the editor, nothing was changed",
          action: { label: "Read", onClick: () => setTab("prompt") },
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
        markSaved(
          fingerprint(
            draft.prompt,
            draft.persona,
            draft.voice,
            draft.guardrails,
            draft.flow ?? null,
            asCard(draft.agentCard),
          ),
        );
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
    // Between Policy and Evals: after the constraints that bound outbound,
    // before the gate that proves it.
    { key: "outbound", label: "Outbound", icon: PhoneOutgoing },
    // After Voice, conceptually — but placed here so the tab strip keeps the
    // authoring tabs together and the operational ones after them. This is what
    // decides which engine the Voice tab's choice actually runs on.
    { key: "bindings", label: "Bindings", icon: Cable },
    { key: "evals", label: "Evals", icon: FlaskConical },
    { key: "ship", label: "Ship", icon: Rocket },
    // Last, because it is the record of everything the tabs before it did.
    // Named "Change log", not "History" — the header's History sheet lists
    // prompt versions, which is a different artefact with a different audience.
    { key: "changelog", label: "Change log", icon: ScrollText },
  ];

  // What a publish is measured against: the live row, and nothing else.
  //
  // This used to read `published`, which falls back to the newest version of
  // any status — on a card that has never shipped, that is the very draft being
  // published. The dialog diffed the draft against itself and reported
  // "+0 · -0 lines" for a publish that introduced the entire prompt.
  // Flow and card are in here because publish sends them. Leaving them out made
  // the dialog's "Full config diff" a diff of four of the six things about to
  // ship, so rewiring the graph or rebinding a connector announced itself as
  // "+0 · −0 lines".
  const publishBaseline = useMemo(
    () => ({
      prompt: publishedRow?.prompt ?? "",
      persona: publishedRow?.persona ?? DEFAULT_PERSONA,
      voice: publishedRow?.voice ?? DEFAULT_VOICE,
      guardrails: publishedRow?.guardrails ?? DEFAULT_GUARDRAILS,
      flow: publishedRow?.flow ?? null,
      agentCard: asCard(publishedRow?.agentCard),
      // Only for a card-less bot; an authored card's rollout lives inside
      // `agentCard.experiment` and is covered by the line above.
      rollout: cardIsAuthored ? null : legacyShipBaseline,
    }),
    [publishedRow, cardIsAuthored, legacyShipBaseline],
  );

  /**
   * The version the editor is currently on had an unreadable stored graph.
   *
   * Read from the row rather than from `flow`, because `flow` has already been
   * degraded to the sentinel by the time it reaches here — which is exactly the
   * ambiguity this flag exists to resolve.
   */
  const flowUnreadable = Boolean(
    (draftId
      ? history.find((v) => v.id === draftId)
      : (history.find((v) => v.status === "published") ?? history[0])
    )?.flowUnreadable,
  );

  const loading = (versionsQuery.isLoading || cardQuery.isPending) && !hydrated;

  /**
   * Why this editor must not render, when it must not.
   *
   * Three distinct states used to collapse into "show the editor anyway":
   *
   * - A URL naming a bot that does not exist. The card GET 404s and nothing
   *   checked it; `/prompt-versions` answers `200 []` for any id, the
   *   empty-history branch seeds defaults, and you get a fully editable studio
   *   whose autosave PATCHes a nonexistent bot.
   * - The card GET failing for any other reason, which is not the same thing
   *   and must not read as "no such bot".
   * - The published-version / active-deployment reads failing. Those two used
   *   to swallow their own errors and answer null, which the header rendered as
   *   "never published" for a card that is live. They now throw, so the reason
   *   is available — and the only correct thing to do with it is say so rather
   *   than let the page make claims about production it cannot support.
   */
  const blocked: { title: string; detail: string } | null = (() => {
    if (loading) return null;
    if (cardQuery.isError) {
      return isNotFound(cardQuery.error)
        ? {
            title: "No agent card with this id",
            detail: `Nothing is registered as “${botId}”. Check the link, or pick a card from the fleet.`,
          }
        : {
            title: "Could not load this agent card",
            detail:
              cardQuery.error instanceof Error
                ? cardQuery.error.message
                : "The API did not answer.",
          };
    }
    if (versionsQuery.isError) {
      return {
        title: "Could not load prompt versions",
        detail:
          versionsQuery.error instanceof Error
            ? versionsQuery.error.message
            : "The API did not answer.",
      };
    }
    // Deliberately NOT blocking on publishedQuery / activeDepQuery: their
    // failure costs the header a lozenge, not the author their editor. It is
    // surfaced inline instead — see `livenessUnknown` below.
    return null;
  })();

  /**
   * The active production deployment could not be read.
   *
   * What the Ship tab says about production — whether this card takes traffic,
   * and whether a rollback target exists — comes from this one query. It used
   * to swallow its own failure and answer null, so an outage rendered as "this
   * card is not deployed". It throws now, and the honest answer to a failed
   * read is "we do not know", not the reassuring one.
   */
  const livenessUnknown = activeDepQuery.isError;
  const currentSnapshot = {
    label: dirty ? `${draftLabel} (draft)` : (published?.label ?? "draft"),
    prompt,
    persona,
    voice,
    guardrails,
    // The other two things a version stores. Omitted, the compare view called a
    // graph rewrite "no changes".
    flow,
    agentCard: asCard(effectiveCard),
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
            void runCompile();
          }}
          onAiReview={() => void onLint(true)}
          lintBusy={lintMutation.isPending}
          onOpenHistory={() => setHistoryOpen(true)}
          versionCount={history.length}
          draftCount={history.filter((v) => v.status === "draft").length}
          publishBlocked={!flowValid}
          flowErrorCount={flowIssues.filter((i) => i.severity === "error").length}
          onFixFlow={() => setTab("flow")}
          deploymentUnknown={livenessUnknown}
        />

        {showGapBanner && (
          <div className="mx-250 mt-150 flex items-start justify-between gap-150 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
            <div>
              <div className="font-semibold text-text-warning-bolder">
                Fixing unanswered question
              </div>
              <div className="mt-025 text-text-warning-bolder/90">
                {gapNote || "Review the system prompt for this coverage gap."}
                {unansweredId ? (
                  <span className="ml-050 font-mono text-body-small text-text-warning-bolder/70">
                    ({unansweredId})
                  </span>
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
        <div className="relative shrink-0 border-b border-border bg-surface">
          <div
            ref={tabStripRef}
            onScroll={syncTabEdges}
            className="scrollbar-none overflow-x-auto px-250"
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
          {/* Each fade appears only while that side actually has tabs behind
              it, so it reads as "there is more this way" rather than as a
              permanent decoration that means nothing. */}
          {!tabEdges.atStart && (
            <div className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-surface to-transparent" />
          )}
          {!tabEdges.atEnd && (
            <div className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-surface to-transparent" />
          )}
        </div>

        {loading ? (
          <div className="grid flex-1 place-items-center p-250">
            <LoadingState label="Loading prompt studio" />
          </div>
        ) : blocked ? (
          <div className="grid flex-1 place-items-center p-250">
            <div className="max-w-md space-y-100 text-center">
              <p className="text-body font-semibold text-text">{blocked.title}</p>
              <p className="text-body-small text-text-subtle">{blocked.detail}</p>
              <button
                onClick={() => void navigate({ to: "/agent-studio" })}
                className="mt-100 inline-flex items-center rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
              >
                Back to the fleet
              </button>
            </div>
          </div>
        ) : (
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
                <AgentGraphTab
                  botId={botId}
                  card={effectiveCard}
                  onChange={(next) => setCard(next)}
                />
              )}
              {tab === "tools" && (
                <ToolsTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
              )}
              {tab === "skills" && (
                <SkillsTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
              )}
              {tab === "connectors" && (
                <ConnectorsTab card={effectiveCard} onChange={(next) => setCard(next)} />
              )}
              {tab === "policy" && <PolicyTab card={effectiveCard} />}
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
                <EvalsTab botId={botId} card={effectiveCard} onChange={(next) => setCard(next)} />
              )}
              {tab === "ship" && (
                <ShipTab
                  botId={botId}
                  value={ship}
                  onChange={setShip}
                  activeDeploymentId={activeDeployment?.id}
                  compileReport={compileReport}
                  onCompile={() => void runCompile()}
                  compileBusy={compileMutation.isPending}
                />
              )}
              {tab === "prompt" && (
                <PromptEditor
                  botId={botId}
                  value={prompt}
                  onChange={setPrompt}
                  onApplyPreset={applyPreset}
                  presets={presets}
                  lintFindings={freshLint}
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
              {tab === "guardrails" && (
                <GuardrailsPanel value={guardrails} onChange={setGuardrails} />
              )}
              {tab === "flow" && (
                <div className="h-full min-h-0">
                  {flowUnreadable ? (
                    // Not "no authored flow". The backend could not parse this
                    // version's stored graph and served the empty sentinel in
                    // its place so the rest of the bot stays reachable; saying
                    // "no authored flow" here would present a corrupt row as a
                    // deliberate choice, and the fix — load the built-in script
                    // or restore an earlier version — is a different fix.
                    <div className="flex h-full flex-col items-center justify-center gap-200 rounded-medium border border-dashed border-border-danger bg-background-danger-subtler/40 text-center">
                      <div className="max-w-lg space-y-100 px-200">
                        <h3 className="heading-small text-text-danger-bolder">
                          This version&apos;s stored graph could not be read
                        </h3>
                        <p className="text-body-small leading-relaxed text-text-subtle">
                          The saved JSON does not match the flow schema, so the editor is showing
                          nothing rather than showing you something that is not what is stored.
                          Nothing has been changed. Restore an earlier version from History, or load
                          the built-in script to start a fresh graph — either one replaces the
                          unreadable row on publish.
                        </p>
                      </div>
                    </div>
                  ) : isEmptyGraph(flow) ? (
                    // An empty flow is meaningful, not missing: the runtime reads
                    // it as "use the built-in collections script". Seeding a graph
                    // on load would silently change what this version does, so it
                    // takes an explicit action.
                    <div className="flex h-full flex-col items-center justify-center gap-200 rounded-medium border border-dashed border-border bg-surface-sunken/40 text-center">
                      <span className="flex size-10 items-center justify-center rounded-medium border border-border bg-surface text-text-subtle">
                        <Workflow className="h-5 w-5" />
                      </span>
                      <div className="max-w-lg space-y-100 px-200">
                        <h3 className="heading-small text-text">No authored flow</h3>
                        <p className="text-body-small leading-relaxed text-text-subtle">
                          This version runs the built-in collections script — Python that publish
                          and rollback cannot touch. Load it here to turn it into a graph you own:
                          it then publishes and rolls back with this prompt version. Nothing changes
                          for live callers until you publish. Set{" "}
                          <code className="font-mono text-text-subtlest">
                            VOICE_FLOW_GRAPH=legacy
                          </code>{" "}
                          to force the built-in script even when a graph exists.
                        </p>
                      </div>
                      <div className="flex flex-wrap justify-center gap-100">
                        <Button
                          variant="primary"
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
                                  err instanceof Error
                                    ? err.message
                                    : "Could not load the built-in flow",
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
          </div>
        )}

        {/* Version history was a permanent 320px rail on every tab but Flow.
            It is a *review* surface — read once or twice a session — and it was
            charging the authoring surfaces a quarter of their width all day for
            that. As a drawer it costs nothing until asked for, and it can be
            wider than 320px when it is. */}
        <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
          <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md">
            <SheetTitle className="sr-only">Version history</SheetTitle>
            <VersionHistory
              versions={history}
              activeDraftId={draftId}
              activeDeployment={activeDeployment}
              priorDeployment={priorDeployment}
              onCompare={(v) => {
                setDiffBase(v);
                setDiffOpen(true);
                setHistoryOpen(false);
              }}
              onRestore={(v) => void restore(v)}
              onLoadDraft={(v) => {
                loadDraft(v);
                setHistoryOpen(false);
              }}
              onDiscardDraft={(v) => discardDraft(v)}
              onRollback={() => void onRollback()}
              rollbackBusy={rollbackMutation.isPending}
            />
          </SheetContent>
        </Sheet>

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
          to={{
            prompt,
            persona,
            voice,
            guardrails,
            flow,
            agentCard: asCard(effectiveCard),
            // Only meaningful for a card-less bot; an authored card carries the
            // same three values inside `agentCard.experiment`, where the card
            // diff already sees them.
            rollout: cardIsAuthored ? null : ship,
          }}
          flowIssues={flowIssues}
          compileReport={compileReport}
          compileError={compileError}
          compileBusy={compileMutation.isPending}
          onConfirm={(note) => void publish(note)}
        />

        {/* Replaces a window.confirm. Same question, asked in the product's own
            surface: themed, keyboard-navigable, escapable, and it names what is
            about to be lost rather than restating the click. */}
        <AlertDialog
          open={presetPending !== null}
          onOpenChange={(open) => {
            if (!open) setPresetPending(null);
          }}
        >
          <AlertDialogContent className="max-w-[28rem]">
            <AlertDialogHeader>
              <AlertDialogTitle>Replace the system prompt?</AlertDialogTitle>
              <AlertDialogDescription>
                Applying <span className="font-medium text-text">{presetShown.current?.label}</span>{" "}
                overwrites the prompt you have written and moves the persona sliders to that
                preset&rsquo;s values.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="rounded-medium border border-border bg-surface-sunken p-100">
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">
                Your current prompt
              </div>
              <p className="line-clamp-3 whitespace-pre-wrap font-mono text-body-small text-text-subtle">
                {prompt.trim()}
              </p>
              <div className="mt-075 text-body-small text-text-subtlest">
                {prompt.length.toLocaleString()} characters. This is a draft edit — nothing
                published changes, and the toast that follows can undo it.
              </div>
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep my prompt</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  if (presetPending) commitPreset(presetPending);
                  setPresetPending(null);
                }}
              >
                Replace with preset
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {busy && (
          <div className="pointer-events-none fixed bottom-4 right-4 rounded-medium bg-background-brand-boldest/90 px-150 py-075 text-body-small text-white shadow-overlay">
            Saving…
          </div>
        )}
      </div>
    </AppShell>
  );
}
