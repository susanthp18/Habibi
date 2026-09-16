import { useCallback, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import type { CompileReport } from "@/api/agent-studio";
import type { PersonaPreset, PromptVersion } from "@/api/types/prompt-studio";
import type { BotDeployment } from "@/api/prompt-studio";
import { useConfirm } from "@/components/ui/use-confirm";
import type { ShipState } from "@/components/prompt-studio/ShipTab";
import { rollbackLive } from "./rollbackLive";
import { EMPTY_FIELDS, adopted, asCard } from "./studioDraft";
import type { useStudioDraft } from "./useStudioDraft";
import type { useStudioQueries } from "./useStudioQueries";

/**
 * What the studio's buttons do: load/discard/restore a version, apply a
 * preset (asking first when there is work to lose), compile, publish, roll
 * back, hand the draft to the sandbox. Every save goes through
 * `editor.flushDraft`, so none of these can fork a draft beside an autosave.
 */
export function useStudioActions({
  botId,
  editor,
  queries,
  history,
  ship,
  activeDeployment,
  priorDeployment,
  flowValid,
  flowUnchecked,
  clearLint,
  onFlowBlocked,
  onPublished,
}: {
  botId: string;
  editor: ReturnType<typeof useStudioDraft>;
  queries: ReturnType<typeof useStudioQueries>;
  history: PromptVersion[];
  ship: ShipState;
  activeDeployment: BotDeployment | null;
  priorDeployment: BotDeployment | null;
  flowValid: boolean;
  flowUnchecked: boolean;
  clearLint: () => void;
  /** Publish was refused for the flow: take the author to it. */
  onFlowBlocked: () => void;
  /** The publish landed: close whatever asked for it. */
  onPublished: () => void;
}) {
  const navigate = useNavigate();
  const { confirm, confirmDialog } = useConfirm();
  const { draft, set, effectiveCard, published, nextLabel, draftLabel, unsaved } = editor;
  const { adoptVersion, markSaved, flushDraft } = editor;
  const { draftId, prompt, persona, voice, guardrails, flow } = draft;
  const {
    versionsQuery,
    cardQuery,
    compileMutation,
    publishMutation,
    restoreMutation,
    discardMutation,
    rollbackMutation,
  } = queries;

  // Preset awaiting confirmation because applying it would discard authored text.
  const [presetPending, setPresetPending] = useState<PersonaPreset | null>(null);
  const [compileReport, setCompileReport] = useState<CompileReport | null>(null);
  /** Why the last compile produced no report. See `runCompile`. */
  const [compileError, setCompileError] = useState<string | null>(null);
  /** Flush + compile. Mutation pending alone left the slider live during save. */
  const [compileBusy, setCompileBusy] = useState(false);

  // Commit a preset. Split from the click handler so the confirmation step can
  // sit between them without the write path knowing a dialog exists.
  const commitPreset = useCallback(
    (p: PersonaPreset) => {
      // Both halves of what a preset writes, and always an Undo: it used to
      // restore the prompt only, so the traits it moved in the same click had
      // no way back short of remembering five numbers.
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

  const applyPreset = useCallback(
    (p: PersonaPreset) => {
      // A preset replaces the whole prompt. Unannounced, that reads as data
      // loss. Ask first when there is work to lose — in the app's own dialog,
      // not window.confirm, which paints as browser chrome and blocks the
      // renderer thread.
      const hasWork = Boolean(prompt.trim()) && prompt !== p.promptTemplate;
      if (hasWork) setPresetPending(p);
      else commitPreset(p);
    },
    [prompt, commitPreset],
  );

  const confirmPreset = useCallback(() => {
    if (presetPending) commitPreset(presetPending);
    setPresetPending(null);
  }, [presetPending, commitPreset]);
  const cancelPreset = useCallback(() => setPresetPending(null), []);

  // One compile, two callers (the Publish button and the Ship tab). Sharing
  // the call is what keeps the two reports describing the same publish.
  const runCompile = useCallback(() => {
    // Never show the last run's gates for this one.
    setCompileReport(null);
    // Flush first: compile and publish must hash the same row. Sending the
    // in-memory mouth without writing it made G-F14 compare the editor's JSON
    // (ints, omitted defaults) to evals that had hashed the mapped draft.
    setCompileBusy(true);
    return flushDraft()
      .then(() =>
        compileMutation.mutateAsync({
          flow: flow ?? undefined,
          agentCard: asCard(effectiveCard) ?? undefined,
          trafficPct: ship.trafficPct,
          autoRollback: ship.autoRollback,
          voice,
          persona,
        }),
      )
      .then((report) => {
        setCompileError(null);
        setCompileReport(report);
      })
      .catch((err: unknown) => {
        // A compile that could not run is not a compile with nothing to say;
        // the publish dialog renders a null report as "no gate section".
        setCompileReport(null);
        setCompileError(err instanceof Error ? err.message : "The compiler did not answer.");
      })
      .finally(() => setCompileBusy(false));
  }, [
    compileMutation,
    flushDraft,
    flow,
    effectiveCard,
    ship.trafficPct,
    ship.autoRollback,
    voice,
    persona,
  ]);

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
        // Explicitly not `published`: on a draft-only card that falls back to
        // `history[0]`, which can BE the row just discarded before the refetch
        // lands -- and autosave would have written it out again as a new draft.
        const live =
          history.find((h) => h.status === "published" && h.id !== v.id) ??
          history.find((h) => h.id !== v.id) ??
          null;
        // Always off the discarded row. Left pointing at it, Publish stayed
        // enabled and republished the text just discarded.
        clearLint();
        if (!live) {
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
      const row = await restoreMutation.mutateAsync(v.id);
      await loadDraft(row);
      toast.info(`Restored ${v.label} into draft — publish to make it live.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Restore failed");
    }
  };

  const publish = async (note: string) => {
    if (!flowValid) {
      toast.error(
        flowUnchecked
          ? "The flow validator could not be reached, so this graph is unchecked. Retry before publishing."
          : "Fix conversation-flow errors before publishing.",
      );
      onFlowBlocked();
      return;
    }
    try {
      // The in-flight autosave lands first; publishing beside it created an
      // orphan or a post-publish duplicate draft.
      const flushed = await flushDraft();
      const row = await publishMutation.mutateAsync({
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
      onPublished();
      adoptVersion({ ...adopted(row), flow: row.flow ?? null }, { draftId: null, status: "idle" });
      clearLint();
      toast.success(`Published ${row.label || nextLabel}`);
      // Publishing a member is a fleet act: every door that merges this card
      // got a new deployment, or says why it kept the old one.
      for (const r of row.fleetRebuilds ?? []) {
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

  const rollback = () =>
    rollbackLive({
      targetId: activeDeployment?.rollbackDeploymentId ?? priorDeployment?.id,
      unsaved,
      confirm,
      rollback: rollbackMutation.mutateAsync,
      refetchVersions: async () => (await versionsQuery.refetch()).data,
      adoptVersion,
    });

  const testSandbox = async () => {
    try {
      // The same save the debounce makes -- with the draft's own summary, not
      // "sandbox try", which the next autosave then flipped back.
      const flushed = unsaved ? await flushDraft() : null;
      const versionId = flushed?.id ?? draftId ?? published?.id;
      if (!versionId) {
        toast.info("No version to test yet.");
        return;
      }
      // botId matters: the sandbox lists versions for the bot it has selected,
      // which defaults to kaia-v2-4; without it a draft belonging to any other
      // card was not found and the page rehearsed kaia's published version.
      void navigate({ to: "/sandbox", search: { promptVersionId: versionId, botId } });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not prepare sandbox draft");
    }
  };

  return {
    presetPending,
    applyPreset,
    confirmPreset,
    cancelPreset,
    compileReport,
    compileError,
    compileBusy,
    runCompile,
    loadDraft,
    discardDraft,
    restore,
    publish,
    rollback,
    testSandbox,
    confirmDialog,
  };
}
