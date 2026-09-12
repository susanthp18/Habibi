/**
 * The editor's state: the six fields a version stores, which draft they belong
 * to, and whether they have been loaded yet.
 *
 * One reducer, because every path that puts a version on screen -- hydration,
 * load draft, discard, publish, rollback -- used to be six `set*` calls and a
 * `fingerprint(...)` copied by hand, and the copies drifted (one forgot the
 * card, one the flow). `adopt` is the one way a version becomes the editor's
 * state; `adopted` is the pure reading of a version every caller shares.
 */
import type { FlowGraph } from "@/api/flow";
import type { AgentCard } from "@/api/agent-card";
import type {
  Guardrails,
  PersonaState,
  PromptVersion,
  VoiceConfig,
} from "@/api/types/prompt-studio";
import { DEFAULT_GUARDRAILS, DEFAULT_PERSONA, DEFAULT_VOICE } from "@/lib/prompt-studio";
import { stableStringify } from "@/lib/stable-stringify";

/** Non-empty object, or null. `{}` is "no card", not "a card with no fields". */
export function asCard(value: unknown): AgentCard | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.keys(value as AgentCard).length ? (value as AgentCard) : null;
}

/** What a version stores and the editor edits. */
export interface EditorFields {
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  /** null until known, so an autosave omits it rather than writing `{}` over a graph. */
  flow: FlowGraph | null;
  card: AgentCard | null;
}

export interface StudioDraftState extends EditorFields {
  /** A version has been put on screen; autosave may run. */
  hydrated: boolean;
  /** The draft the autosave writes to; null creates one. */
  draftId: string | null;
  /** Set by the "replace unreadable graph" buttons only; cleared by the next save. */
  replaceUnreadable: boolean;
}

export const EMPTY_FIELDS: EditorFields = {
  prompt: "",
  persona: DEFAULT_PERSONA,
  voice: DEFAULT_VOICE,
  guardrails: DEFAULT_GUARDRAILS,
  flow: null,
  card: null,
};

export const INITIAL_STATE: StudioDraftState = {
  ...EMPTY_FIELDS,
  hydrated: false,
  draftId: null,
  replaceUnreadable: false,
};

/**
 * The editor fields a version puts on screen.
 *
 * `?? DEFAULT_*`: the three are non-null on every row served today, but a null
 * would put `undefined` into state that half a dozen tabs dereference. An
 * unreadable stored graph reads as null, not as the `{}` sentinel the wire
 * materialises -- the sentinel would be autosaved over the column.
 */
export function adopted(
  v: PromptVersion,
  card: AgentCard | null = asCard(v.agentCard),
): EditorFields {
  return {
    prompt: v.prompt,
    persona: v.persona ?? DEFAULT_PERSONA,
    voice: v.voice ?? DEFAULT_VOICE,
    guardrails: v.guardrails ?? DEFAULT_GUARDRAILS,
    flow: v.flowUnreadable ? null : (v.flow ?? null),
    card,
  };
}

/**
 * Identity of the editor's state, for "is this dirty?" and "has this been
 * saved?". `stableStringify`, because local state and the server's echo build
 * the same objects in different key orders.
 */
export function fingerprintOf(f: EditorFields): string {
  return stableStringify({
    p: f.prompt,
    persona: f.persona,
    voice: f.voice,
    g: f.guardrails,
    flow: f.flow,
    card: f.card,
  });
}

type Setter<T> = T | ((prev: T) => T);

export type StudioDraftAction =
  | { type: "reset" }
  | { type: "adopt"; fields: EditorFields; draftId: string | null }
  | { type: "prompt"; value: Setter<string> }
  | { type: "persona"; value: Setter<PersonaState> }
  | { type: "voice"; value: Setter<VoiceConfig> }
  | { type: "guardrails"; value: Setter<Guardrails> }
  | { type: "flow"; value: Setter<FlowGraph | null> }
  | { type: "card"; value: AgentCard | null }
  | { type: "draftId"; value: string | null }
  | { type: "replaceUnreadable"; value: boolean };

function resolve<T>(value: Setter<T>, prev: T): T {
  return typeof value === "function" ? (value as (p: T) => T)(prev) : value;
}

export function studioDraftReducer(
  state: StudioDraftState,
  action: StudioDraftAction,
): StudioDraftState {
  switch (action.type) {
    case "reset":
      return INITIAL_STATE;
    case "adopt":
      return { ...state, ...action.fields, draftId: action.draftId, hydrated: true };
    case "prompt":
      return { ...state, prompt: resolve(action.value, state.prompt) };
    case "persona":
      return { ...state, persona: resolve(action.value, state.persona) };
    case "voice":
      return { ...state, voice: resolve(action.value, state.voice) };
    case "guardrails":
      return { ...state, guardrails: resolve(action.value, state.guardrails) };
    case "flow":
      return { ...state, flow: resolve(action.value, state.flow) };
    case "card":
      return { ...state, card: action.value };
    case "draftId":
      return { ...state, draftId: action.value };
    case "replaceUnreadable":
      return { ...state, replaceUnreadable: action.value };
  }
}
