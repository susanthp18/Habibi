import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { useBlocker } from "@tanstack/react-router";
import type { useEnsureStudioDraft } from "@/api/prompt-studio";
import type { FlowGraph } from "@/api/flow";
import type {
  Guardrails,
  PersonaState,
  PromptVersion,
  VoiceConfig,
} from "@/api/types/prompt-studio";
import { stableStringify } from "@/lib/stable-stringify";
import type { AgentCard } from "@/api/agent-card";

export type SaveStatus = "idle" | "saving" | "saved" | "error";

/** Non-empty object, or null. `{}` is "no card", not "a card with no fields". */
export function asCard(value: unknown): AgentCard | null {
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
export function fingerprint(
  p: string,
  persona: PersonaState,
  voice: VoiceConfig,
  g: Guardrails,
  flow: FlowGraph | null,
  card: AgentCard | null,
) {
  return stableStringify({ p, persona, voice, g, flow, card });
}

/**
 * The draft-save machinery: `runSave`, `flushDraft`, the route blocker and the
 * debounced autosave. The refs it writes are owned by the page, because the
 * hydration effect declared before this hook reads them too.
 */
export function useStudioDraft({
  botId,
  ensureDraft,
  prompt,
  persona,
  voice,
  guardrails,
  flow,
  effectiveCard,
  draftId,
  draftLabel,
  replaceUnreadable,
  hydrated,
  cardRefused,
  dirty,
  autosaveNonce,
  lastSavedFp,
  autosaveTimer,
  skipAutosave,
  savingRef,
  resaveRef,
  unsavedRef,
  saveInFlight,
  saveFailures,
  draftSummary,
  markSaved,
  setSaveStatus,
  setAutosaveNonce,
  setDraftId,
  setReplaceUnreadable,
}: {
  botId: string;
  ensureDraft: ReturnType<typeof useEnsureStudioDraft>["mutateAsync"];
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  flow: FlowGraph | null;
  effectiveCard: AgentCard;
  draftId: string | null;
  draftLabel: string;
  replaceUnreadable: boolean;
  hydrated: boolean;
  cardRefused: boolean;
  dirty: boolean;
  autosaveNonce: number;
  lastSavedFp: RefObject<string>;
  autosaveTimer: RefObject<number | null>;
  skipAutosave: RefObject<boolean>;
  savingRef: RefObject<boolean>;
  resaveRef: RefObject<boolean>;
  unsavedRef: RefObject<boolean>;
  saveInFlight: RefObject<Promise<PromptVersion | null> | null>;
  saveFailures: RefObject<number>;
  draftSummary: RefObject<string>;
  markSaved: (fp: string) => void;
  setSaveStatus: Dispatch<SetStateAction<SaveStatus>>;
  setAutosaveNonce: Dispatch<SetStateAction<number>>;
  setDraftId: Dispatch<SetStateAction<string | null>>;
  setReplaceUnreadable: Dispatch<SetStateAction<boolean>>;
}) {
  /**
   * What a save would send, read at call time rather than captured.
   *
   * `runSave` and `flushDraft` are stable callbacks; the editor state they
   * write is whatever is on screen when they run, which is the property that
   * lets Publish, Test-in-Sandbox and route changes flush the same draft the
   * debounce would have.
   */
  const editorRef = useRef({
    prompt,
    persona,
    voice,
    guardrails,
    flow,
    card: asCard(effectiveCard),
    draftId,
    draftLabel,
    replaceUnreadable,
  });
  editorRef.current = {
    prompt,
    persona,
    voice,
    guardrails,
    flow,
    card: asCard(effectiveCard),
    draftId,
    draftLabel,
    replaceUnreadable,
  };

  /**
   * The one way a draft is written. Autosave, Publish, Test in Sandbox and
   * Load/Restore all come through here; three of them used to call
   * `ensureDraft` on their own, outside the in-flight guard, and a click inside
   * the debounce window forked a second draft.
   */
  const runSave = useCallback(async (): Promise<PromptVersion | null> => {
    if (savingRef.current) {
      // Queue behind the save already running rather than racing it.
      resaveRef.current = true;
      return saveInFlight.current;
    }
    const e = editorRef.current;
    const fpSent = fingerprint(e.prompt, e.persona, e.voice, e.guardrails, e.flow, e.card);
    savingRef.current = true;
    setSaveStatus("saving");
    const work = (async () => {
      try {
        const draft = await ensureDraft({
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
        setDraftId(draft.id);
        // The replacement is stored, so the next autosave is an ordinary one
        // again. Left set, a later accidental sentinel would sail through the
        // guard this flag exists to open.
        if (e.replaceUnreadable) setReplaceUnreadable(false);
        // The baseline is what was *sent*, not the echoed row. The server
        // normalises structured fields (`entryFor: []`, `style: null`), so
        // fingerprinting the echo left the chip on "unsaved" forever after
        // "Start from blank" or adding a flow node.
        markSaved(fpSent);
        saveFailures.current = 0;
        setSaveStatus("saved");
        return draft;
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
    // The refs and state setters are stable; they are listed only because the
    // linter cannot see that through a prop.
  }, [
    ensureDraft,
    markSaved,
    botId,
    draftSummary,
    resaveRef,
    saveFailures,
    saveInFlight,
    savingRef,
    setAutosaveNonce,
    setDraftId,
    setReplaceUnreadable,
    setSaveStatus,
  ]);

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
    const fp = fingerprint(e.prompt, e.persona, e.voice, e.guardrails, e.flow, e.card);
    if (fp !== lastSavedFp.current && (e.draftId || e.prompt.trim())) {
      last = await runSave();
    }
    return last;
  }, [runSave, autosaveTimer, lastSavedFp, saveInFlight]);

  // SHELL-9: a route change flushes the draft first, and a tab close asks.
  useBlocker({
    shouldBlockFn: async () => {
      if (!unsavedRef.current) return false;
      await flushDraft();
      return false;
    },
    enableBeforeUnload: () => unsavedRef.current,
  });

  // Debounced autosave while dirty.
  useEffect(() => {
    if (!hydrated || skipAutosave.current) return;
    // Never autosave against a card the API could not confirm exists. On a dead
    // URL `/prompt-versions` still answers `200 []`, so hydration succeeds and
    // every keystroke used to PATCH a bot id nothing is registered under.
    if (cardRefused) return;
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
      void runSave();
    }, 1200);

    return () => {
      if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    };
  }, [
    prompt,
    persona,
    voice,
    guardrails,
    flow,
    effectiveCard,
    dirty,
    hydrated,
    autosaveNonce,
    runSave,
    cardRefused,
    autosaveTimer,
    lastSavedFp,
    setSaveStatus,
    skipAutosave,
  ]);

  return { runSave, flushDraft };
}
