import { useCallback, useMemo, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { VersionHistory } from "@/components/prompt-studio/VersionHistory";
import { DiffModal } from "@/components/prompt-studio/DiffModal";
import { PublishDialog } from "@/components/prompt-studio/PublishDialog";
import type { PromptVersion } from "@/api/types/prompt-studio";
import {
  DEFAULT_GUARDRAILS,
  DEFAULT_PERSONA,
  DEFAULT_VOICE,
  languageTag,
} from "@/lib/prompt-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useCompilePreview } from "@/api/agent-studio";
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
import { useStudioActions } from "@/components/prompt-studio/studio/useStudioActions";
import { CardStaleBanner, GapBanner } from "@/components/prompt-studio/studio/StudioBanners";
import { asCard } from "@/components/prompt-studio/studio/studioDraft";

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
  const queries = useStudioQueries(botId);
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
  } = queries;
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
  const [tab, setTab] = useState<Tab>("prompt");
  const readFindings = useCallback(() => setTab("prompt"), []);
  const lint = useStudioLint({ prompt, guardrails, lintMutation, onRead: readFindings });
  const flowCheck = useFlowValidation(flow, tab === "flow");
  const [diffOpen, setDiffOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [diffBase, setDiffBase] = useState<PromptVersion | undefined>();
  // The API, not a hardcoded copy. `?? PRESETS` made an empty persona_presets
  // table look populated — and the rows only ever existed in a migration that
  // a fresh install stamps rather than replays, so a new database showed four
  // presets that were not there and applied templates from nowhere.
  const presets = useMemo(() => presetsQuery.data ?? [], [presetsQuery.data]);
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

  const [publishOpen, setPublishOpen] = useState(false);
  const closePublish = useCallback(() => setPublishOpen(false), []);
  const goToFlow = useCallback(() => setTab("flow"), []);
  const actions = useStudioActions({
    botId,
    editor,
    queries,
    history,
    ship,
    activeDeployment,
    priorDeployment,
    flowValid: flowCheck.valid,
    flowUnchecked: flowCheck.unchecked,
    clearLint: lint.clear,
    onFlowBlocked: goToFlow,
    onPublished: closePublish,
  });
  const { compileReport } = actions;

  // The Tools tab has always had a live grant, because it runs its own
  // preview. The Flow tab read `compileReport`, which is null until somebody
  // presses Publish or Compile -- so the canvas's "not on this card" chip was
  // invisible in an ordinary authoring session. Same preview, same card.
  const flowPreview = useCompilePreview(botId, { agentCard: effectiveCard }, hydrated);
  const grantTools = compileReport?.effective_tools ?? flowPreview.data?.effective_tools;

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
        onTestSandbox: () => void actions.testSandbox(),
        onPublish: () => {
          setPublishOpen(true);
          void actions.runCompile();
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
          {cardStale && <CardStaleBanner botId={botId} error={cardQuery.error} />}
          <GapBanner botId={botId} unansweredId={unansweredId} note={gapNote} />
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
          runCompile={() => void actions.runCompile()}
          compileBusy={compileMutation.isPending}
          applyPreset={actions.applyPreset}
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
              void actions.restore(v);
              setHistoryOpen(false);
            }}
            onLoadDraft={(v) => {
              void actions.loadDraft(v);
              setHistoryOpen(false);
            }}
            onDiscardDraft={(v) => actions.discardDraft(v)}
            onRollback={() => void actions.rollback()}
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
        compileError={actions.compileError}
        compileBusy={compileMutation.isPending}
        busy={publishMutation.isPending}
        onConfirm={(note) => void actions.publish(note)}
      />

      <PresetConfirm
        pending={actions.presetPending}
        prompt={prompt}
        onCancel={actions.cancelPreset}
        onConfirm={actions.confirmPreset}
      />

      {busy && (
        <div className="pointer-events-none fixed bottom-4 right-4 rounded-medium bg-background-brand-boldest/90 px-150 py-075 text-body-small text-white shadow-overlay">
          Saving…
        </div>
      )}
      {actions.confirmDialog}
    </PromptStudioShell>
  );
}
