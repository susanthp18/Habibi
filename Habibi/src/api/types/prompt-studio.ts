/**
 * Domain / wire types for the prompt-studio surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

import type { FlowGraph } from "../flow";

export type PersonaTraitKey = "empathy" | "firmness" | "formality" | "verbosity" | "upsell";
export type PersonaState = {
  traits: Record<PersonaTraitKey, number>;
  language: string;
  fallbackLanguages: string[];
};
/** A provider-declared control's value. Scalars only — see `VoiceConfig.params`. */
export type VoiceParamValue = string | number | boolean;
export type VoiceConfig = {
  voiceId: string;
  /** Azure ShortName — authoritative for TTS when set. */
  azureVoiceName?: string;
  /** Optional express-as style when the catalog voice supports it. */
  style?: string | null;
  speed: number; // 0.5 - 1.5
  pitch: number; // -6 to +6
  warmth: number; // 0-100
  pauseMs: number; // 100 - 800
  sampleText: string;
  /**
   * The selected model's own controls, keyed by its `params_schema`.
   *
   * The five fields above are Azure's, because Azure was the only provider when
   * this type was written. They are not a superset of anything: Fish S2.1 Pro
   * has a temperature and no pitch, Deepgram Aura-2 has almost no prosody at
   * all. Those controls used to live in VoicePanel's local state and nowhere
   * else — so they changed the preview, did not mark the editor dirty, did not
   * survive a tab switch, and were not published.
   *
   * Being on `VoiceConfig` is what fixes all four: it autosaves, it diffs, and
   * `db._prompt_voice` folds it into `AgentTuning.tts.params`, which
   * `voice.tuning_apply.tts_settings_kwargs` hands to the bound provider.
   *
   * Untyped by key on purpose. The authority on which keys a model accepts is
   * that model's Pipecat `Settings` class, and the provider factory filters
   * against it; a second opinion here would go stale the moment a vendor adds
   * a knob.
   */
  params?: Record<string, VoiceParamValue>;
};
export type Guardrails = {
  prohibited: string[];
  escalateAbuse: boolean;
  escalateLegal: boolean;
  neverQuoteRate: boolean;
  neverPromiseWaiver: boolean;
  alwaysDiscloseRecording: boolean;
  refusePoliticsReligion: boolean;
  maxTurns: number;
  maxSeconds: number;
};
export type PromptVersion = {
  id: string;
  label: string; // "v1.4"
  author: string;
  status: "published" | "archived" | "draft";
  createdAt: string; // ISO
  summary: string;
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  /** Authored conversation graph; absent on versions predating flow authoring. */
  flow?: FlowGraph;
  /**
   * The stored graph could not be parsed, and `flow` above is the empty
   * sentinel standing in for it.
   *
   * Mirrors `PromptVersionResponse.flowUnreadable`. The backend degrades rather
   * than raising because the alternative is a 500 on every version of the bot
   * — see `db._prompt_flow` — and this flag is what stops the degradation from
   * reading as "this version never authored a flow".
   */
  flowUnreadable?: boolean;
  botId?: string;
  agentCard?: Record<string, unknown>;
  /** On a publish response: what every door that merges this card did with
   *  the news -- a new deployment, or a named reason it kept the old one. */
  fleetRebuilds?: FleetRebuild[] | null;
};

export type FleetRebuild = {
  doorBotId: string;
  rebuilt: boolean;
  reason?: string | null;
  deploymentId?: string | null;
  previousDeploymentId?: string | null;
  bundleHash?: string | null;
};
export type PersonaPreset = {
  id: string;
  label: string;
  description: string;
  traits: Record<PersonaTraitKey, number>;
  promptTemplate: string;
};
export type TtsVoice = {
  id: string;
  name: string;
  gender: "Female" | "Male";
  accent: string;
  duration: string;
};
export type LanguageName =
  "English" | "Hindi" | "Tamil" | "Telugu" | "Kannada" | "Marathi" | "Bengali" | "Gujarati";
// Very small line-level diff (LCS)
export type DiffLine = { kind: "same" | "add" | "del"; text: string };
