import { useCallback, useMemo, useRef, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { VersionHistory } from "@/components/prompt-studio/VersionHistory";
import { DiffModal } from "@/components/prompt-studio/DiffModal";
import { PublishDialog } from "@/components/prompt-studio/PublishDialog";
import type { PersonaPreset, PromptVersion } from "@/api/types/prompt-studio";
import {
  DEFAULT_GUARDRAILS,
  DEFAULT_PERSONA,
  DEFAULT_VOICE,
  languageTag,
} from "@/lib/prompt-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useConfirm } from "@/components/ui/use-confirm";
import { rollbackLive } from "@/components/prompt-studio/studio/rollbackLive";
import { useCompilePreview, type CompileReport } from "@/api/agent-studio";
import { isNotFound } from "@/api/config";
import { asRollbackTriggers, type AgentCard } from "@/api/agent-card";
import { type ShipState } from "@/components/prompt-studio/ShipTab";
import { PromptStudioShell, type Tab } from "@/components/prompt-studio/studio/PromptStudioShell";
import { useStudioQueries } from "@/components/prompt-studio/studio/useStudioQueries";
import { StudioTabBody } from "@/components/prompt-studio/studio/StudioTabBody";
import { PresetConfirm } from "@/components/prompt-studio/studio/PresetConfirm";
import { useStudioDraft } from "@/components/prompt-studio/studio/useStudioDraft";
import { useFlowValidation } from "@/components/prompt-studio/studio/useFlowValidation";
import { useStudioLint } from "@/components/prompt-studio/studio/useStudioLint";
import { EMPTY_FIELDS, adopted, asCard } from "@/components/prompt-studio/studio/studioDraft";

export const Route = createLazyFileRoute("/_app/agent-studio/$botId")({
  component: AgentCardEditor,
});

function AgentCardEditor() {
  const { botId } = Route.useParams();
  const { unansweredId, note } = Route.useSearch();
  // Keyed, so switching cards remounts the editor instead of re-running it with
  // the previous card's state still loaded.
  //
  // This route reuses one component instance across botIds, and the editor
  // holds a lot of state the server does not re-supply on a param change: the
  // version list, lint findings, flow issues, save status, the compile report,
  // canary settings. Resetting them by hand means a growing list that has to be
  // updated every time someone adds a field — and the failure is silent, a chip
  // from the previous card sitting in the header of this one. A key cannot rot.
  return <PromptStudioPage key={botId} botId={botId} unansweredId={unansweredId} note={note} />;
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
  const {
    versionsQuery,
    presetsQuery,
    activeDepQuery,
    publishedQuery,
    prodDepsQuery,
    experimentsQuery,
    cardQuery,
    cardRefused,
    cardStale,
    compileMutation,
    publishMutation,
    restoreMutation,
    ensureDraftMutation,
    discardMutation,
    rollbackMutation,
    lintMutation,
  } = useStudioQueries(botId);
  const ensureDraft = ensureDraftMutation.mutateAsync;

  // The version list is the query's; the page keeps no mirror of it.
  const history = useMemo(() => versionsQuery.data ?? [], [versionsQuery.data]);
  const editor = useStudioDraft({
    botId,
    ensureDraft,
    history,
    card: cardQuery.data,
    cardPending: cardQuery.isPending,
    cardRefused,
    publishedRow: publishedQuery.data,
  });
  const {
    draft,
    set,
    effectiveCard,
    published,
    publishedRow,
    nextLabel,
    draftLabel,
    dirty,
    unsaved,
    saveStatus,
    adoptVersion,
    markSaved,
    flushDraft,
  } = editor;
  const { hydrated, draftId, prompt, persona, voice, guardrails, flow } = draft;
  // Preset awaiting confirmation because applying it would discard authored text.
  const [presetPending, setPresetPending] = useState<PersonaPreset | null>(null);
  // The dialog animates out over ~150ms, and it reads its subject from
  // `presetPending` — which is already null by then, so the sentence degraded to
  // "Applying  overwrites the prompt…" on the way out. Hold the last subject so
  // the closing frame says the same thing the open one did.
  const presetShown = useRef<PersonaPreset | null>(null);
  if (presetPending) presetShown.current = presetPending;
  const [tab, setTab] = useState<Tab>("prompt");
  const readFindings = useCallback(() => setTab("prompt"), []);
  const lint = useStudioLint({ prompt, guardrails, lintMutation, onRead: readFindings });
  const clearLint = lint.clear;
  const flowCheck = useFlowValidation(flow, tab === "flow");
  const [diffOpen, setDiffOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [diffBase, setDiffBase] = useState<PromptVersion | undefined>();
  const [publishOpen, setPublishOpen] = useState(false);
  const [compileReport, setCompileReport] = useState<CompileReport | null>(null);
  /** Why the last compile produced no report. See `runCompile`. */
  const [compileError, setCompileError] = useState<string | null>(null);
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

  // Canary settings are a card field, not editor-local state. Keeping them
  // separate meant they never marked the editor dirty, never autosaved, and
  // were invisible to the compile preview — which read `card.experiment` and
  // cheerfully reported "full ship" for a publish that then 422'd at 40%.
  // The Tools tab has always had a live grant, because it runs its own preview.
  // The Flow tab read `compileReport`, which is null until somebody presses
  // Publish or Compile and is reset to null on every recompile — so the canvas's
  // "not on this card" chip, the whole point of FLOW-3, was invisible in an
  // ordinary authoring session and stale afterwards. Two tabs of one editor
  // disagreeing about the same card's grant is the drift this phase is removing.
  const flowPreview = useCompilePreview(botId, { agentCard: effectiveCard }, hydrated);
  const grantTools = compileReport?.effective_tools ?? flowPreview.data?.effective_tools;

  const ship = useMemo<ShipState>(() => {
    const exp = effectiveCard.experiment;
    return {
      trafficPct: typeof exp?.traffic_pct === "number" ? exp.traffic_pct : 100,
      autoRollback: asRollbackTriggers(exp?.auto_rollback),
    };
  }, [effectiveCard]);

  const setShip = (next: ShipState) => {
    set.card({
      ...effectiveCard,
      experiment: {
        traffic_pct: next.trafficPct,
        auto_rollback: next.autoRollback,
      },
    });
  };

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
      set.prompt(p.promptTemplate);
      set.persona((s) => ({ ...s, traits: p.traits }));
      clearLint();
      toast.success(`Applied ${p.label}`, {
        action: {
          label: "Undo",
          onClick: () => {
            set.prompt(previousPrompt);
            set.persona((s) => ({ ...s, traits: previousTraits }));
            clearLint();
          },
        },
      });
    },
    [prompt, persona.traits, clearLint, set],
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

  const loadDraft = async (v: PromptVersion) => {
    // Up to a full autosave window of authored text used to go with the
    // switch. It is written to the draft it belongs to first.
    await flushDraft();
    // The draft's own summary rides along, so autosave keeps the note
    // restore-as-draft wrote ("restored from v1.2") instead of "draft autosave".
    adoptVersion(
      { ...adopted(v), flow: v.flow ?? null },
      { draftId: v.id, summary: v.summary, status: "saved" },
    );
    clearLint();
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
        // Always off the discarded row. Left pointing at it, Publish stayed
        // enabled and republished the text just discarded.
        clearLint();
        if (!live) {
          // Nothing else to show: the seeded defaults, as a bot with no version
          // starts. Keeping the discarded text on screen let autosave write it
          // straight back out as a new draft.
          adoptVersion(
            { ...EMPTY_FIELDS, card: asCard(cardQuery.data?.publishedCard) },
            { draftId: null, status: "idle" },
          );
          markSaved("");
        } else {
          adoptVersion(
            { ...adopted(live), flow: live.flow ?? null },
            { draftId: null, status: "idle" },
          );
        }
      }
      toast.success(`Discarded draft ${v.label || v.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Discard failed");
    }
  };

  const restore = async (v: PromptVersion) => {
    try {
      await flushDraft();
      const draft = await restoreMutation.mutateAsync(v.id);
      await loadDraft(draft);
      toast.info(`Restored ${v.label} into draft — publish to make it live.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Restore failed");
    }
  };

  const { confirm, confirmDialog } = useConfirm();

  const publish = async (note: string) => {
    if (!flowCheck.valid) {
      toast.error(
        flowCheck.unchecked
          ? "The flow validator could not be reached, so this graph is unchecked. Retry before publishing."
          : "Fix conversation-flow errors before publishing.",
      );
      setTab("flow");
      return;
    }
    try {
      // The in-flight autosave lands first; publishing beside it created an
      // orphan or a post-publish duplicate draft.
      const flushed = await flushDraft();
      const publishedRow = await publishMutation.mutateAsync({
        draftId: flushed?.id ?? draftId,
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
        autoRollback: ship.autoRollback,
      });
      setPublishOpen(false);
      adoptVersion(
        { ...adopted(publishedRow), flow: publishedRow.flow ?? null },
        { draftId: null, status: "idle" },
      );
      clearLint();
      toast.success(`Published ${publishedRow.label || nextLabel}`);
      // Publishing a member is a fleet act: every door that merges this card
      // got a new deployment, or says why it kept the old one. Silence here
      // would mean the hop keeps speaking the previous graph and nobody knew.
      for (const r of publishedRow.fleetRebuilds ?? []) {
        if (r.rebuilt) {
          toast.info(`${r.doorBotId} rebuilt its fleet bundle (${r.deploymentId})`);
        } else if (r.reason !== "unchanged") {
          toast.warning(`${r.doorBotId} did not rebuild its fleet bundle: ${r.reason}`);
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Publish failed");
    }
  };

  const onRollback = () =>
    rollbackLive({
      targetId: activeDeployment?.rollbackDeploymentId ?? priorDeployment?.id,
      unsaved,
      confirm,
      rollback: rollbackMutation.mutateAsync,
      refetchVersions: async () => (await versionsQuery.refetch()).data,
      adoptVersion,
    });

  const onTestSandbox = async () => {
    try {
      // The same save the debounce makes -- with the draft's own summary, not
      // "sandbox try", which the next autosave then flipped back.
      const flushed = dirty ? await flushDraft() : null;
      const versionId = flushed?.id ?? draftId ?? published?.id;
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
    }),
    [publishedRow],
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
    if (cardRefused) {
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
    <PromptStudioShell
      header={{
        cardName: cardQuery.data?.name,
        currentVersion: publishedRow?.label ?? "—",
        canPublish: Boolean(draftId) || dirty,
        nextVersion: draftLabel,
        dirty: unsaved,
        personaLabel,
        saveStatus,
        onTestSandbox: () => void onTestSandbox(),
        onPublish: () => {
          setPublishOpen(true);
          void runCompile();
        },
        onAiReview: () => void lint.critique(),
        lintBusy: lint.busy,
        onOpenHistory: () => setHistoryOpen(true),
        versionCount: history.length,
        draftCount: history.filter((v) => v.status === "draft").length,
        publishBlocked: !flowCheck.valid,
        flowErrorCount: flowCheck.errorCount,
        flowUnchecked: flowCheck.unchecked,
        onFixFlow: () => setTab("flow"),
        deploymentUnknown: livenessUnknown,
      }}
      banners={
        <>
          {cardStale && (
            <div className="mx-250 mt-150 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
              The card could not be re-read (
              {cardQuery.error instanceof Error
                ? cardQuery.error.message
                : "the API did not answer"}
              ). You are editing the copy loaded earlier; saves still go to {botId}.
            </div>
          )}

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
        </>
      }
      tab={tab}
      setTab={setTab}
    >
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
        <StudioTabBody
          tab={tab}
          botId={botId}
          fields={draft}
          set={set}
          effectiveCard={effectiveCard}
          draftId={draftId}
          ship={ship}
          setShip={setShip}
          activeDeployment={activeDeployment}
          priorDeployment={priorDeployment}
          compileReport={compileReport}
          runCompile={() => void runCompile()}
          compileBusy={compileMutation.isPending}
          applyPreset={applyPreset}
          presets={presets}
          presetsFailed={presetsQuery.isError}
          freshLint={lint.findings}
          lintFailed={lint.failed}
          lintPending={lint.pending}
          cardLocales={cardLocales}
          flowUnreadable={flowUnreadable}
          setReplaceUnreadable={set.replaceUnreadable}
          onFlowValidation={flowCheck.onValidation}
          grantTools={grantTools}
        />
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
            onRestore={(v) => {
              void restore(v);
              setHistoryOpen(false);
            }}
            onLoadDraft={(v) => {
              void loadDraft(v);
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
        }}
        flowIssues={flowCheck.issues}
        compileReport={compileReport}
        compileError={compileError}
        compileBusy={compileMutation.isPending}
        busy={publishMutation.isPending}
        onConfirm={(note) => void publish(note)}
      />

      <PresetConfirm
        pending={presetPending}
        shown={presetShown.current}
        prompt={prompt}
        onCancel={() => setPresetPending(null)}
        onConfirm={() => {
          if (presetPending) commitPreset(presetPending);
          setPresetPending(null);
        }}
      />

      {busy && (
        <div className="pointer-events-none fixed bottom-4 right-4 rounded-medium bg-background-brand-boldest/90 px-150 py-075 text-body-small text-white shadow-overlay">
          Saving…
        </div>
      )}
      {confirmDialog}
    </PromptStudioShell>
  );
}
