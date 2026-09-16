import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useBlocker } from "@tanstack/react-router";
import type { useEnsureStudioDraft } from "@/api/prompt-studio";
import type { FlowGraph } from "@/api/flow";
import type { PromptVersion } from "@/api/types/prompt-studio";
import type { AgentCard } from "@/api/agent-card";
import { nextVersionLabel } from "@/lib/prompt-studio";
import {
  EMPTY_FIELDS,
  INITIAL_STATE,
  adopted,
  asCard,
  fingerprintOf,
  hydrationStart,
  studioDraftReducer,
  studioHydrationBlocked,
  versionHasAuthoring,
  type EditorFields,
} from "./studioDraft";

export type SaveStatus = "idle" | "saving" | "saved" | "error";

/**
 * The editor: what is on screen, what was last saved, and the one way a draft
 * is written.
 *
 * Owns the reducer, hydration from the version list, the saved baseline and
 * everything derived from it (`dirty`, `unsaved`, the labels), the debounced
 * autosave, `flushDraft` and the route blocker. The page keeps queries, UI
 * state and actions; every save -- autosave, Publish, Test in Sandbox,
 * Load/Restore -- comes through `flushDraft` here, so a click inside the
 * debounce window can never fork a second draft.
 */
export function useStudioDraft({
  botId,
  ensureDraft,
  history,
  card: cardRow,
  cardPending,
  historyReady,
  cardRefused,
  publishedRow: publishedFromQuery,
}: {
  botId: string;
  ensureDraft: ReturnType<typeof useEnsureStudioDraft>["mutateAsync"];
  /** The version list, newest first; the page keeps no mirror of it. */
  history: PromptVersion[];
  /** The card read: its resolved (draft-aware) card and the published one. */
  card: { agentCard?: AgentCard; publishedCard?: AgentCard } | null | undefined;
  cardPending: boolean;
  /** False until `/prompt-versions` has settled, including `200 []`. */
  historyReady: boolean;
  cardRefused: boolean;
  /** `/prompt-versions/published`, when it answered. */
  publishedRow: PromptVersion | null | undefined;
}) {
  const [draft, dispatch] = useReducer(studioDraftReducer, INITIAL_STATE);
  const { hydrated, draftId, prompt, persona, voice, guardrails, flow, card, replaceUnreadable } =
    draft;
  const set = useMemo(
    () => ({
      prompt: (value: string) => dispatch({ type: "prompt", value }),
      persona: (
        value: EditorFields["persona"] | ((p: EditorFields["persona"]) => EditorFields["persona"]),
      ) => dispatch({ type: "persona", value }),
      voice: (value: EditorFields["voice"]) => dispatch({ type: "voice", value }),
      guardrails: (value: EditorFields["guardrails"]) => dispatch({ type: "guardrails", value }),
      flow: (value: FlowGraph | null | ((p: FlowGraph | null) => FlowGraph | null)) =>
        dispatch({ type: "flow", value }),
      card: (value: AgentCard | null) => dispatch({ type: "card", value }),
      replaceUnreadable: (value: boolean) => dispatch({ type: "replaceUnreadable", value }),
    }),
    [],
  );

  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
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
  /** `unsaved`, readable from the route blocker. */
  const unsavedRef = useRef(false);
  /** The save in flight, so anything that must not race it can await it. */
  const saveInFlight = useRef<Promise<PromptVersion | null> | null>(null);
  /** Consecutive failed autosaves; the retry backs off and gives up at three. */
  const saveFailures = useRef(0);
  /**
   * The summary autosave writes onto the open draft. A ref because nothing
   * renders it and changing it must not re-run the autosave effect. It exists
   * so that a draft created by restore-as-draft keeps its "restored from vX"
   * note: autosave used to send a literal "draft autosave" on every write.
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

  /**
   * Put a version on screen as the saved baseline: hydration, load draft,
   * discard, publish and rollback all come through here. Autosave is held off
   * until after paint so the adoption itself is never written back.
   */
  const adoptVersion = useCallback(
    (
      fields: EditorFields,
      opts: { draftId: string | null; summary?: string; status?: SaveStatus },
    ) => {
      skipAutosave.current = true;
      dispatch({ type: "adopt", fields, draftId: opts.draftId });
      draftSummary.current = opts.summary || "draft autosave";
      markSaved(fingerprintOf(fields));
      if (opts.status) setSaveStatus(opts.status);
      window.setTimeout(() => {
        skipAutosave.current = false;
      }, 0);
    },
    [markSaved],
  );

  const cardFromRow = cardRow?.agentCard;
  const publishedCardFromRow = cardRow?.publishedCard;

  // Hydrate the editor once the version list AND the card read have settled.
  // `/prompt-versions` answers `200 []` for any id at all, so hydrating before
  // the card read would produce a fully editable studio for a dead URL, with
  // autosave pointed at it. Hydrating before the version list settles is the
  // other failure: the first paint sees `history=[]`, seeds EMPTY_FIELDS, and
  // never adopts the published prompt when History 15 lands.
  useEffect(() => {
    if (studioHydrationBlocked({ cardPending, historyReady, hydrated })) return;
    if (!history.length) {
      // A bot row with no prompt version at all. Seed the defaults so the
      // first version can be authored; an empty editor is the baseline, not a
      // saved state. `adoptVersion` already records that fingerprint — do not
      // `markSaved("")` here: that made the empty seed look unsaved and the
      // autosave timer created a blank draft (`v1.7` / "draft autosave").
      adoptVersion({ ...EMPTY_FIELDS, card: asCard(cardFromRow) }, { draftId: null });
      return;
    }
    // Resume a draft only when it has authoring. A blank autosave draft must
    // not hide the published prompt.
    const start = hydrationStart(history);
    if (!start) {
      adoptVersion({ ...EMPTY_FIELDS, card: asCard(cardFromRow) }, { draftId: null });
      return;
    }
    const resumeDraft =
      start.status === "draft" && versionHasAuthoring(start) ? start : undefined;
    adoptVersion(adopted(start), {
      draftId: resumeDraft?.id ?? null,
      summary: resumeDraft?.summary,
    });
  }, [history, historyReady, hydrated, cardFromRow, cardPending, adoptVersion]);

  // Baseline for `dirty`: the live row if there is one, else the newest version
  // of any status — for a clone with only a draft, that draft is the right
  // thing to diff against.
  const published = useMemo(
    () => history.find((v) => v.status === "published") ?? history[0],
    [history],
  );

  // The actually-published row, or nothing. The header used `published` and so
  // called a never-published clone's draft "published".
  const publishedRow = useMemo(
    () => publishedFromQuery ?? history.find((v) => v.status === "published") ?? null,
    [publishedFromQuery, history],
  );

  // What the tabs render and what every save sends. Local edits win; otherwise
  // the server's resolved card (draft-aware), then the version's own card.
  // A plain `??` chain was wrong here — the server returns `{}` for a card-less
  // bot, and `{} ?? x` is `{}`, so every cloned agent showed empty tabs.
  const effectiveCard = useMemo<AgentCard>(
    () => card ?? asCard(cardFromRow) ?? asCard(published?.agentCard) ?? {},
    [card, cardFromRow, published],
  );

  const fields = useMemo(
    () => ({ prompt, persona, voice, guardrails, flow, card: asCard(effectiveCard) }),
    [prompt, persona, voice, guardrails, flow, effectiveCard],
  );

  const dirty = useMemo(() => {
    // No version to compare against: anything authored is a change. Returning
    // false here is what silently disabled autosave on a brand-new bot.
    if (!published) return hydrated && Boolean(prompt.trim());
    // `flow` and the card belong in the fingerprint: without them a canvas edit
    // or a Skills/Tools toggle never recomputed `dirty`, so the debounced
    // autosave never fired and the edit was lost on navigate.
    return (
      fingerprintOf(fields) !==
      fingerprintOf({
        ...adopted(published, asCard(publishedCardFromRow) ?? asCard(published.agentCard)),
        flow: published.flow ?? null,
      })
    );
  }, [fields, prompt, published, hydrated, publishedCardFromRow]);

  // "Unsaved" is not "differs from what is live". On a card that has already
  // shipped, a saved draft differs from the published row for as long as it
  // exists — so the header's chip read "unsaved · draft v1.1" for the whole
  // session, including the instant after an autosave landed, and "Draft saved"
  // could never appear. This compares against what was last written instead.
  // savedTick is the dependency that makes reading the ref safe: it changes
  // whenever markSaved moves the baseline.
  const unsaved = useMemo(
    () => hydrated && fingerprintOf(fields) !== lastSavedFp.current,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- savedTick stands in for the ref
    [fields, hydrated, savedTick],
  );
  unsavedRef.current = unsaved;

  // Derived from the live row, not `published` — for a clone that fell through
  // to the draft's own label, and `nextVersionLabel("Collections-clone v1")`
  // does not match /^v\d+\.\d+$/, so it silently produced "v1.0".
  //
  // A card that has never published mints v1.0, not v1.1 -- the seed label is
  // the first version, not the predecessor of one. And a live label that is
  // not `v<major>.<minor>` (a restored row once carried its id) bumps from the
  // newest matching label in history rather than resetting to v1.0.
  const nextLabel = useMemo(() => {
    if (!publishedRow) return "v1.0";
    if (/^v\d+\.\d+$/.test(publishedRow.label ?? "")) return nextVersionLabel(publishedRow.label);
    const newest = history
      .map((v) => v.label ?? "")
      .filter((l) => /^v\d+\.\d+$/.test(l))
      .sort((a, b) => {
        const [am = 0, an = 0] = a.slice(1).split(".").map(Number);
        const [bm = 0, bn = 0] = b.slice(1).split(".").map(Number);
        return bm - am || bn - an;
      })[0];
    return newest ? nextVersionLabel(newest) : "v1.0";
  }, [publishedRow, history]);

  // A draft keeps the name it was created with; `nextLabel` only names a new
  // one. Autosave used to PATCH `label: nextLabel` onto the existing draft, so
  // the first keystroke renamed "Collections-clone v1" to "v1.0".
  const draftLabel = useMemo(
    () => history.find((v) => v.id === draftId)?.label || nextLabel,
    [history, draftId, nextLabel],
  );

  /**
   * What a save would send, read at call time rather than captured, so
   * `runSave` and `flushDraft` are stable and write whatever is on screen when
   * they run.
   */
  const editorRef = useRef({ ...fields, draftId, draftLabel, replaceUnreadable });
  editorRef.current = { ...fields, draftId, draftLabel, replaceUnreadable };

  /** The one way a draft is written. */
  const runSave = useCallback(async (): Promise<PromptVersion | null> => {
    if (savingRef.current) {
      // Queue behind the save already running rather than racing it.
      resaveRef.current = true;
      return saveInFlight.current;
    }
    const e = editorRef.current;
    const fpSent = fingerprintOf(e);
    savingRef.current = true;
    setSaveStatus("saving");
    const work = (async () => {
      try {
        const row = await ensureDraft({
          draftId: e.draftId,
          label: e.draftLabel,
          prompt: e.prompt,
          persona: e.persona,
          voice: e.voice,
          guardrails: e.guardrails,
          flow: e.flow ?? undefined,
          replaceUnreadable: e.replaceUnreadable,
          agentCard: e.card ?? undefined,
          summary: draftSummary.current,
          botId,
        });
        dispatch({ type: "draftId", value: row.id });
        // The replacement is stored, so the next autosave is an ordinary one
        // again. Left set, a later accidental sentinel would sail through the
        // guard this flag exists to open.
        if (e.replaceUnreadable) dispatch({ type: "replaceUnreadable", value: false });
        // The baseline is what was *sent*, not the echoed row. The server
        // normalises structured fields (`entryFor: []`, `style: null`), so
        // fingerprinting the echo left the chip on "unsaved" forever after
        // "Start from blank" or adding a flow node.
        markSaved(fpSent);
        saveFailures.current = 0;
        setSaveStatus("saved");
        return row;
      } catch {
        setSaveStatus("error");
        // Retry with backoff, three times; an edit lost to one failed PATCH
        // was gone the moment the author navigated.
        saveFailures.current += 1;
        if (saveFailures.current <= 3) {
          window.setTimeout(
            () => setAutosaveNonce((n) => n + 1),
            2000 * 2 ** (saveFailures.current - 1),
          );
        }
        return null;
      } finally {
        savingRef.current = false;
        saveInFlight.current = null;
        if (resaveRef.current) {
          resaveRef.current = false;
          // Re-enter the effect so the edits made mid-save are written too.
          setAutosaveNonce((n) => n + 1);
        }
      }
    })();
    saveInFlight.current = work;
    return work;
  }, [ensureDraft, markSaved, botId]);

  /**
   * Write whatever is unsaved, now, and return the draft it landed in.
   *
   * Cancels the debounce, waits for a save already in flight, then saves once
   * more if the editor moved on since. `null` when there was nothing to write
   * and no draft exists.
   */
  const flushDraft = useCallback(async (): Promise<PromptVersion | null> => {
    if (autosaveTimer.current) {
      window.clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    }
    let last: PromptVersion | null = null;
    if (saveInFlight.current) last = await saveInFlight.current;
    const e = editorRef.current;
    if (fingerprintOf(e) !== lastSavedFp.current && (e.draftId || e.prompt.trim())) {
      last = await runSave();
    }
    return last;
  }, [runSave]);

  // SHELL-9: a route change flushes the draft first, and a tab close asks.
  useBlocker({
    shouldBlockFn: async () => {
      if (!unsavedRef.current) return false;
      await flushDraft();
      return false;
    },
    enableBeforeUnload: () => unsavedRef.current,
  });

  // Debounced autosave while the editor differs from what was last written.
  // `dirty` is "differs from live" and stays true for the whole life of a
  // saved draft, so gating the timer on it either skipped a revert-to-live
  // that still needed writing, or kept offering to save a draft that already
  // had been.
  useEffect(() => {
    if (!hydrated || skipAutosave.current) return;
    // Never autosave against a card the API could not confirm exists. On a dead
    // URL `/prompt-versions` still answers `200 []`, so hydration succeeds and
    // every keystroke used to PATCH a bot id nothing is registered under.
    if (cardRefused) return;
    if (!unsaved) {
      // "saved" survives here. The refetch that follows an autosave used to
      // make `dirty` (vs live) flicker and reset the status to "idle" —
      // wiping the "Draft saved" confirmation before it could paint.
      setSaveStatus((s) => (s === "saving" || s === "saved" ? s : "idle"));
      return;
    }

    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    autosaveTimer.current = window.setTimeout(() => {
      const e = editorRef.current;
      // Same predicate as `flushDraft`. The timer used to call `runSave`
      // unguarded, so an empty first paint POSTed a blank draft and the next
      // load adopted it over the published prompt.
      if (!e.draftId && !e.prompt.trim()) return;
      void runSave();
    }, 1200);

    return () => {
      if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    };
  }, [fields, unsaved, hydrated, autosaveNonce, runSave, cardRefused]);

  return {
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
  };
}
