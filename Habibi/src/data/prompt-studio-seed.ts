// Persona & Prompt Studio seed + helpers (deterministic, in-memory)

import type { FlowGraph } from "@/api/flow";

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

/**
 * Variables a *system* prompt may interpolate. Mirrors
 * ``prompt_render.SYSTEM_SAFE_VARIABLES`` — static operator facts, never a
 * customer-controlled field.
 */
export const SYSTEM_SAFE_VARIABLES = [
  "agent_name",
  "bank_name",
  "language",
  "time_of_day",
] as const;

/**
 * CRM fields. Known to the platform, but **not substituted in a system
 * prompt**: `render_system_prompt` only fills SYSTEM_SAFE_VARIABLES, and
 * `strip_unrendered_crm_tokens` then deletes every line that still holds one.
 * They live on the untrusted CRM context card the runtime attaches instead.
 *
 * Kept as its own list so the editor can say which is which. Offering all nine
 * in one undifferentiated palette is how "Reference their account
 * {account_no}" got written into a prompt and then silently vanished from the
 * live policy — the author had no way to know the difference.
 */
export const CRM_VARIABLES = [
  "customer_name",
  "account_no",
  "overdue_amount",
  "due_date",
  "last_payment",
] as const;

export const KNOWN_VARIABLES: string[] = [...CRM_VARIABLES, ...SYSTEM_SAFE_VARIABLES];

/**
 * Flow-tab variable syntax, mirroring `voice/flow_vars.py::_TEMPLATE_RE`.
 *
 * `{{ customer_name }}` in a **flow node** substitutes the real CRM value.
 * `{customer_name}` in a **prompt** deletes the line it sits on. Same studio,
 * near-identical tokens, opposite behaviour — and a double-brace token in a
 * prompt matches neither the substitution regex nor the CRM stripper, so it is
 * not rendered, not dropped and (until now) not reported: it reaches the model
 * verbatim and the braces are spoken aloud.
 */
const FLOW_TOKEN_RE = /\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g;

/** Flow-syntax tokens typed into a prompt — each is read out, braces and all. */
export function detectFlowVars(prompt: string): string[] {
  return Array.from(new Set(Array.from(prompt.matchAll(FLOW_TOKEN_RE)).map((m) => m[1])));
}

/** Single-brace prompt tokens. Mirrors `prompt_render.TOKEN_RE`. */
const PROMPT_TOKEN_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

/**
 * Single-brace token names, with flow tokens blanked out first.
 *
 * `{{customer_name}}` — no inner spaces — literally contains
 * `{customer_name}`, so an unmasked scan reports the same characters as both a
 * flow-syntax error and a CRM warning, giving the author two contradictory
 * remedies for one token. Blanked to spaces rather than removed so any future
 * caller that wants offsets still gets true ones. Same masking as
 * `prompt_lint.lint_prompt`.
 */
function promptTokens(prompt: string): string[] {
  const masked = prompt.replace(FLOW_TOKEN_RE, (m) => " ".repeat(m.length));
  return Array.from(masked.matchAll(PROMPT_TOKEN_RE)).map((m) => m[1]);
}

/** CRM tokens present in a template — each one costs its whole line at runtime. */
export function detectCrmVars(prompt: string): string[] {
  const crm = new Set<string>(CRM_VARIABLES);
  return Array.from(new Set(promptTokens(prompt).filter((v) => crm.has(v))));
}

export const TTS_VOICES: TtsVoice[] = [
  { id: "priya", name: "Priya", gender: "Female", accent: "Indian English", duration: "0:03" },
  { id: "anjali", name: "Anjali", gender: "Female", accent: "Hindi-English", duration: "0:03" },
  { id: "neha", name: "Neha", gender: "Female", accent: "Neutral English", duration: "0:03" },
  { id: "ravi", name: "Ravi", gender: "Male", accent: "Indian English", duration: "0:03" },
  { id: "arjun", name: "Arjun", gender: "Male", accent: "Hindi-English", duration: "0:03" },
  { id: "kabir", name: "Kabir", gender: "Male", accent: "Neutral English", duration: "0:03" },
];

/**
 * The languages a card may be authored in, with the BCP-47 tag each one binds.
 *
 * Mirrors `agent_core/languages.py`, which is the authority — the tag is what
 * configures the recogniser, and a display name is not convertible to one by
 * guesswork ("Bengali" is bn-IN here and bn-BD one border away). Held here as
 * pairs rather than bare names so this list cannot grow an entry the runtime
 * has no tag for; `test_language_registry_drift` holds the two together.
 */
export const LANGUAGE_ENTRIES = [
  { name: "English", tag: "en-IN" },
  { name: "Hindi", tag: "hi-IN" },
  { name: "Tamil", tag: "ta-IN" },
  { name: "Telugu", tag: "te-IN" },
  { name: "Kannada", tag: "kn-IN" },
  { name: "Marathi", tag: "mr-IN" },
  { name: "Bengali", tag: "bn-IN" },
  { name: "Gujarati", tag: "gu-IN" },
] as const;

export type LanguageName = (typeof LANGUAGE_ENTRIES)[number]["name"];

export const LANGUAGES: string[] = LANGUAGE_ENTRIES.map((l) => l.name);

/** BCP-47 tag a display name binds, or undefined when it is not one of ours. */
export function languageTag(name: string): string | undefined {
  return LANGUAGE_ENTRIES.find((l) => l.name.toLowerCase() === name.trim().toLowerCase())?.tag;
}

// Mirrors the persona_presets rows these stand in for, and CRM-token-free
// for the same reason those are: every runtime renders a system prompt with
// render_system_prompt and then deletes any line still holding a CRM token.
// A mock that ships {customer_name} teaches the pattern that gets the line
// silently dropped in production, which is exactly how the live Collections
// prompt ended up losing two of its six lines.
const EMPATHETIC_PROMPT = `You are {agent_name}, an inbound collections voice agent for {bank_name}.
Greet the caller warmly and acknowledge their situation before discussing dues.
Their account number, outstanding balance and due date arrive in the CRM context card — quote those figures verbatim and never invent one.
Speak in {language}. Be patient, empathetic and non-judgemental.
Never threaten legal action. Offer Promise-to-Pay options when the caller signals hardship.`;

const FIRM_PROMPT = `You are {agent_name}, a collections agent for {bank_name}.
Address the caller directly and state the purpose of the call within the first two sentences.
State the overdue amount and due date from the CRM context card, exactly as given. Never estimate or round them.
Speak in {language}. Be concise and outcome-focused; ask for a specific payment date.
Never threaten legal action and never imply consequences the bank has not authorised.`;

const COMPLIANCE_PROMPT = `You are {agent_name}, a compliance-first collections agent for {bank_name}.
Verify the caller's identity before sharing any account information.
Account details are in the CRM context card and may only be discussed after verification succeeds.
Speak in {language}. Keep to the script; if a request falls outside policy, say so plainly and escalate.
Never quote an interest rate, waiver or settlement figure that a tool has not returned.`;

const UPSELL_PROMPT = `You are {agent_name}, a collections and relationship voice agent for {bank_name}.
Resolve the caller's query about their overdue balance first — the figures are in the CRM context card.
Only once the collections matter is settled and sentiment is not negative, mention at most one offer returned by recommend_next_offer.
Speak in {language}. Never name a product the tool did not give you.`;

export const PRESETS: PersonaPreset[] = [
  {
    id: "empathetic",
    label: "Empathetic Collector",
    description: "Warm, patient, hardship-aware",
    traits: { empathy: 82, firmness: 40, formality: 55, verbosity: 60, upsell: 20 },
    promptTemplate: EMPATHETIC_PROMPT,
  },
  {
    id: "firm",
    label: "Firm Collector",
    description: "Direct, outcome-focused",
    traits: { empathy: 35, firmness: 80, formality: 65, verbosity: 40, upsell: 15 },
    promptTemplate: FIRM_PROMPT,
  },
  {
    id: "compliance",
    label: "Compliance-First",
    description: "Every disclosure, every time",
    traits: { empathy: 55, firmness: 55, formality: 90, verbosity: 55, upsell: 5 },
    promptTemplate: COMPLIANCE_PROMPT,
  },
  {
    id: "upsell",
    label: "Upsell-Focused",
    description: "Resolve, then convert",
    traits: { empathy: 65, firmness: 45, formality: 55, verbosity: 55, upsell: 75 },
    promptTemplate: UPSELL_PROMPT,
  },
];

export const DEFAULT_GUARDRAILS: Guardrails = {
  prohibited: ["guarantee", "police", "arrest", "threaten", "family will pay", "harassment"],
  escalateAbuse: true,
  escalateLegal: true,
  neverQuoteRate: true,
  neverPromiseWaiver: true,
  alwaysDiscloseRecording: true,
  refusePoliticsReligion: true,
  maxTurns: 20,
  maxSeconds: 480,
};

export const DEFAULT_VOICE: VoiceConfig = {
  voiceId: "priya",
  azureVoiceName: "en-IN-AartiNeural",
  speed: 1.0,
  pitch: 0,
  warmth: 62,
  pauseMs: 320,
  sampleText:
    "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
};

export const DEFAULT_PERSONA: PersonaState = {
  traits: PRESETS[0].traits,
  language: "English",
  fallbackLanguages: ["Hindi"],
};

export const VERSION_HISTORY: PromptVersion[] = [
  {
    id: "v1_4",
    label: "v1.4",
    author: "Anita Rao",
    status: "published",
    createdAt: new Date(Date.now() - 2 * 86400_000).toISOString(),
    summary: "+ recording disclosure, empathy 70→75",
    prompt: EMPATHETIC_PROMPT,
    persona: { ...DEFAULT_PERSONA, traits: { ...PRESETS[0].traits, empathy: 75 } },
    voice: { ...DEFAULT_VOICE },
    guardrails: { ...DEFAULT_GUARDRAILS },
  },
  {
    id: "v1_3",
    label: "v1.3",
    author: "Anita Rao",
    status: "archived",
    createdAt: new Date(Date.now() - 6 * 86400_000).toISOString(),
    summary: "+ upsell-focused fallback path",
    prompt: EMPATHETIC_PROMPT.replace(
      "Offer Promise-to-Pay",
      "Offer Promise-to-Pay or product upgrade",
    ),
    persona: { ...DEFAULT_PERSONA, traits: { ...PRESETS[0].traits, upsell: 40 } },
    voice: { ...DEFAULT_VOICE, warmth: 55 },
    guardrails: { ...DEFAULT_GUARDRAILS, neverPromiseWaiver: false },
  },
  {
    id: "v1_2",
    label: "v1.2",
    author: "Vikram Shah",
    status: "archived",
    createdAt: new Date(Date.now() - 12 * 86400_000).toISOString(),
    summary: "− legal-threat language, + Hindi fallback",
    prompt: FIRM_PROMPT,
    persona: {
      ...DEFAULT_PERSONA,
      traits: PRESETS[1].traits,
      fallbackLanguages: ["Hindi", "Marathi"],
    },
    voice: { ...DEFAULT_VOICE, voiceId: "ravi" },
    guardrails: { ...DEFAULT_GUARDRAILS, prohibited: ["police", "arrest", "harassment"] },
  },
  {
    id: "v1_1",
    label: "v1.1",
    author: "Vikram Shah",
    status: "archived",
    createdAt: new Date(Date.now() - 20 * 86400_000).toISOString(),
    summary: "initial compliance pass",
    prompt: COMPLIANCE_PROMPT.replace("Never quote interest rates.", ""),
    persona: { ...DEFAULT_PERSONA, traits: PRESETS[2].traits },
    voice: { ...DEFAULT_VOICE, warmth: 45 },
    guardrails: { ...DEFAULT_GUARDRAILS, neverQuoteRate: false },
  },
  {
    id: "v1_0",
    label: "v1.0",
    author: "Anita Rao",
    status: "archived",
    createdAt: new Date(Date.now() - 30 * 86400_000).toISOString(),
    summary: "first draft",
    prompt: "You are BigBound AI. Collect the overdue amount.",
    persona: DEFAULT_PERSONA,
    voice: DEFAULT_VOICE,
    guardrails: {
      ...DEFAULT_GUARDRAILS,
      prohibited: [],
      alwaysDiscloseRecording: false,
      escalateAbuse: false,
    },
  },
];

// ---------- helpers ----------

export function detectUndefinedVars(prompt: string, known = KNOWN_VARIABLES): string[] {
  return Array.from(new Set(promptTokens(prompt).filter((v) => !known.includes(v))));
}

export function renderPersonaPreview(state: PersonaState): string {
  const { empathy, firmness, formality, verbosity, upsell } = state.traits;
  const greeting =
    formality > 65
      ? "Good afternoon, Mr. Sharma."
      : empathy > 60
        ? "Namaste Rahul-ji,"
        : "Hi Rahul,";
  const empathyLine =
    empathy > 70
      ? "I completely understand this month has been difficult, and I'm here to help."
      : empathy > 40
        ? "I know these calls aren't easy — I appreciate you picking up."
        : "";
  const purposeLine =
    firmness > 70
      ? "I'm calling about the overdue EMI of ₹18,450 on your loan account, past due since the 5th."
      : "I'm calling regarding your EMI of ₹18,450 for this cycle.";
  const optionsLine =
    verbosity > 55
      ? "We have a few options — you can settle today via UPI, split into two parts this week, or set a promise-to-pay for a date that works for you."
      : "Would you like to settle today, or set a promise-to-pay?";
  const upsellLine =
    upsell > 55
      ? " Also, since your repayment history has been good in prior cycles, you're pre-approved for a personal loan top-up we can discuss after this."
      : "";
  return [greeting, empathyLine, purposeLine, optionsLine].filter(Boolean).join(" ") + upsellLine;
}

// Very small line-level diff (LCS)
export type DiffLine = { kind: "same" | "add" | "del"; text: string };
export function diffPrompts(a: string, b: string): DiffLine[] {
  const A = a.split("\n");
  const B = b.split("\n");
  const m = A.length,
    n = B.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0,
    j = 0;
  while (i < m && j < n) {
    if (A[i] === B[j]) {
      out.push({ kind: "same", text: A[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "del", text: A[i++] });
    } else {
      out.push({ kind: "add", text: B[j++] });
    }
  }
  while (i < m) out.push({ kind: "del", text: A[i++] });
  while (j < n) out.push({ kind: "add", text: B[j++] });
  return out;
}

/** Fallback length/4 heuristic — live Studio uses POST /prompt-versions/estimate-tokens (tiktoken). */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export function nextVersionLabel(current: string): string {
  // "v1.4" -> "v1.5"
  const m = current.match(/^v(\d+)\.(\d+)$/);
  if (!m) return "v1.0";
  return `v${m[1]}.${Number(m[2]) + 1}`;
}

/** Serialize persona/voice/guardrails for line-level diffs alongside the prompt. */
export function formatConfigBlock(
  label: string,
  persona: PersonaState,
  voice: VoiceConfig,
  guardrails: Guardrails,
): string {
  const traits = persona.traits;
  return [
    `## ${label}`,
    "### Persona",
    `language: ${persona.language}`,
    `fallbacks: ${(persona.fallbackLanguages || []).join(", ") || "—"}`,
    `empathy: ${traits.empathy}`,
    `firmness: ${traits.firmness}`,
    `formality: ${traits.formality}`,
    `verbosity: ${traits.verbosity}`,
    `upsell: ${traits.upsell}`,
    "### Voice",
    `voiceId: ${voice.voiceId}`,
    // Both are authoritative: azureVoiceName is what the TTS request actually
    // uses and style drives express-as. Leaving them out of the diff meant
    // switching the neural voice or the speaking style showed as no change.
    `azureVoiceName: ${voice.azureVoiceName || "—"}`,
    `style: ${voice.style || "—"}`,
    `speed: ${voice.speed}`,
    `pitch: ${voice.pitch}`,
    `warmth: ${voice.warmth}`,
    `pauseMs: ${voice.pauseMs}`,
    // One line per control, sorted, so the diff shows *which* knob moved rather
    // than one long re-ordered object line changing wholesale. Key order out of
    // a JSON round-trip is not stable enough to diff against.
    ...Object.entries(voice.params ?? {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, val]) => `param.${key}: ${String(val)}`),
    "### Guardrails",
    `prohibited: ${(guardrails.prohibited || []).join(", ") || "—"}`,
    `escalateAbuse: ${guardrails.escalateAbuse}`,
    `escalateLegal: ${guardrails.escalateLegal}`,
    `neverQuoteRate: ${guardrails.neverQuoteRate}`,
    `neverPromiseWaiver: ${guardrails.neverPromiseWaiver}`,
    `alwaysDiscloseRecording: ${guardrails.alwaysDiscloseRecording}`,
    `refusePoliticsReligion: ${guardrails.refusePoliticsReligion}`,
    `maxTurns: ${guardrails.maxTurns}`,
    `maxSeconds: ${guardrails.maxSeconds}`,
  ].join("\n");
}

export function diffStudioVersions(
  base: { prompt: string; persona: PersonaState; voice: VoiceConfig; guardrails: Guardrails },
  current: { prompt: string; persona: PersonaState; voice: VoiceConfig; guardrails: Guardrails },
): DiffLine[] {
  const a = [
    "### System prompt",
    ...base.prompt.split("\n"),
    "",
    ...formatConfigBlock("Config", base.persona, base.voice, base.guardrails).split("\n"),
  ].join("\n");
  const b = [
    "### System prompt",
    ...current.prompt.split("\n"),
    "",
    ...formatConfigBlock("Config", current.persona, current.voice, current.guardrails).split("\n"),
  ].join("\n");
  return diffPrompts(a, b);
}
