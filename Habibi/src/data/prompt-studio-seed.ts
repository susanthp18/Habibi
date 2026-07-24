// Persona & Prompt Studio seed + helpers (deterministic, in-memory)

export type PersonaTraitKey = "empathy" | "firmness" | "formality" | "verbosity" | "upsell";

export type PersonaState = {
  traits: Record<PersonaTraitKey, number>;
  language: string;
  fallbackLanguages: string[];
};

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

export const KNOWN_VARIABLES = [
  "customer_name",
  "account_no",
  "overdue_amount",
  "due_date",
  "last_payment",
  "agent_name",
  "bank_name",
  "language",
  "time_of_day",
];

export const TTS_VOICES: TtsVoice[] = [
  { id: "priya", name: "Priya", gender: "Female", accent: "Indian English", duration: "0:03" },
  { id: "anjali", name: "Anjali", gender: "Female", accent: "Hindi-English", duration: "0:03" },
  { id: "neha", name: "Neha", gender: "Female", accent: "Neutral English", duration: "0:03" },
  { id: "ravi", name: "Ravi", gender: "Male", accent: "Indian English", duration: "0:03" },
  { id: "arjun", name: "Arjun", gender: "Male", accent: "Hindi-English", duration: "0:03" },
  { id: "kabir", name: "Kabir", gender: "Male", accent: "Neutral English", duration: "0:03" },
];

export const LANGUAGES = ["English", "Hindi", "Tamil", "Telugu", "Kannada", "Marathi", "Bengali", "Gujarati"];

const EMPATHETIC_PROMPT = `You are {agent_name}, an inbound collections voice agent for {bank_name}.
Greet {customer_name} warmly and acknowledge their situation before discussing dues.
Reference their account {account_no} and the overdue amount of {overdue_amount} due on {due_date}.
Speak in {language}. Be patient, empathetic and non-judgemental.
Always disclose that the call is recorded for quality and compliance.
Never threaten legal action. Offer Promise-to-Pay options when the customer signals hardship.`;

const FIRM_PROMPT = `You are {agent_name}, a BigBound AI agent for {bank_name}.
Address {customer_name} directly and state the purpose of the call within the first two sentences.
Clearly state the overdue amount {overdue_amount} on account {account_no}, past due since {due_date}.
Speak in {language}. Be professional, direct and outcome-oriented.
Disclose call recording. Do not promise waivers. Escalate to a human on any dispute.`;

const COMPLIANCE_PROMPT = `You are {agent_name}, a compliance-first BigBound AI agent for {bank_name}.
Begin every call with the recording disclosure and verify caller identity before sharing any account information.
Reference {customer_name}, account {account_no}, dues {overdue_amount}, due on {due_date} only after verification.
Speak in {language}. Never quote interest rates. Never promise fee waivers. Escalate on any dispute or hardship signal.`;

const UPSELL_PROMPT = `You are {agent_name}, a collections + relationship voice agent for {bank_name}.
Resolve {customer_name}'s query about their overdue {overdue_amount} on account {account_no} first.
Once the primary query is addressed, and eligibility permits, gently introduce one relevant product offer.
Speak in {language}. Do not push if the customer is stressed or has raised a dispute.`;

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
  sampleText: "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
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
    prompt: EMPATHETIC_PROMPT.replace("Offer Promise-to-Pay", "Offer Promise-to-Pay or product upgrade"),
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
    persona: { ...DEFAULT_PERSONA, traits: PRESETS[1].traits, fallbackLanguages: ["Hindi", "Marathi"] },
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
  const matches = Array.from(prompt.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g)).map((m) => m[1]);
  return Array.from(new Set(matches.filter((v) => !known.includes(v))));
}

export function renderPersonaPreview(state: PersonaState): string {
  const { empathy, firmness, formality, verbosity, upsell } = state.traits;
  const greeting = formality > 65 ? "Good afternoon, Mr. Sharma." : empathy > 60 ? "Namaste Rahul-ji," : "Hi Rahul,";
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
    `speed: ${voice.speed}`,
    `pitch: ${voice.pitch}`,
    `warmth: ${voice.warmth}`,
    `pauseMs: ${voice.pauseMs}`,
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

