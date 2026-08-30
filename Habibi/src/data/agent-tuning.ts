/** AgentTuning — single struct for Sandbox Studio, voice.bot, and Promote bundle. */

export type AgentTuningLlm = {
  temperature: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  max_completion_tokens: number;
  seed: number | null;
};

export type AgentTuningTts = {
  voice: string;
  style: string;
  style_degree: string;
  rate: string;
  pitch: string;
  volume: string;
  emphasis: string | null;
  text_aggregation_mode: "SENTENCE" | "TOKEN";
};

export type AgentTuningStt = {
  language: string;
  profanity: "raw" | "masked" | "removed";
};

export type AgentTuningVad = {
  confidence: number;
  start_secs: number;
  stop_secs: number;
  min_volume: number;
};

export type AgentTuningTurn = {
  stop_secs: number;
  pre_speech_ms: number;
  max_duration_secs: number;
};

export type BargeInMode = "on" | "min_words" | "locked";
export type MuteStrategyId = "until_first_bot_complete" | "during_function_calls";
export type IdleLadderStep = "nudge" | "direct" | "close";

export type AgentTuningInteraction = {
  barge_in: BargeInMode;
  min_words: number;
  mute: MuteStrategyId[];
  idle_timeout_secs: number;
  idle_ladder: IdleLadderStep[];
};

export type AgentTuning = {
  llm: AgentTuningLlm;
  tts: AgentTuningTts;
  stt: AgentTuningStt;
  vad: AgentTuningVad;
  turn: AgentTuningTurn;
  interaction: AgentTuningInteraction;
};

export type AgentTuningPreset = {
  id: string;
  label: string;
  summary: string;
  tuning: AgentTuning;
};

export const DEFAULT_AGENT_TUNING: AgentTuning = {
  llm: {
    temperature: 0.4,
    top_p: 0.9,
    frequency_penalty: 0.3,
    presence_penalty: 0.0,
    max_completion_tokens: 220,
    seed: null,
  },
  tts: {
    voice: "en-IN-AartiNeural",
    style: "empathetic",
    style_degree: "1.4",
    rate: "1.05",
    pitch: "+2%",
    volume: "default",
    emphasis: null,
    text_aggregation_mode: "SENTENCE",
  },
  stt: {
    language: "en-IN",
    profanity: "raw",
  },
  vad: {
    confidence: 0.7,
    start_secs: 0.15,
    stop_secs: 0.2,
    min_volume: 0.6,
  },
  turn: {
    stop_secs: 3.0,
    pre_speech_ms: 0,
    max_duration_secs: 8.0,
  },
  interaction: {
    barge_in: "on",
    min_words: 3,
    mute: ["until_first_bot_complete", "during_function_calls"],
    idle_timeout_secs: 6.0,
    idle_ladder: ["nudge", "direct", "close"],
  },
};

export const AGENT_TUNING_PRESETS: AgentTuningPreset[] = [
  {
    id: "empathetic-collections",
    label: "Empathetic-collections",
    summary: "Default warm collections tone",
    tuning: DEFAULT_AGENT_TUNING,
  },
  {
    id: "brisk-verification",
    label: "Brisk-verification",
    summary: "Faster, firmer ID check",
    tuning: {
      ...DEFAULT_AGENT_TUNING,
      llm: { ...DEFAULT_AGENT_TUNING.llm, temperature: 0.25, max_completion_tokens: 160 },
      tts: {
        ...DEFAULT_AGENT_TUNING.tts,
        style: "friendly",
        style_degree: "1.1",
        rate: "1.12",
      },
      interaction: {
        ...DEFAULT_AGENT_TUNING.interaction,
        barge_in: "min_words",
        min_words: 2,
        idle_timeout_secs: 5,
      },
    },
  },
  {
    id: "firm-legal",
    label: "Firm-legal",
    summary: "Lower warmth, precise wording",
    tuning: {
      ...DEFAULT_AGENT_TUNING,
      llm: {
        ...DEFAULT_AGENT_TUNING.llm,
        temperature: 0.2,
        frequency_penalty: 0.5,
        max_completion_tokens: 200,
      },
      tts: {
        ...DEFAULT_AGENT_TUNING.tts,
        style: "empathetic",
        style_degree: "1.0",
        rate: "0.98",
        pitch: "0%",
      },
      interaction: {
        ...DEFAULT_AGENT_TUNING.interaction,
        barge_in: "locked",
        idle_timeout_secs: 8,
      },
    },
  },
  {
    id: "low-latency-demo",
    label: "Low-latency-demo",
    summary: "TOKEN aggregation, short answers",
    tuning: {
      ...DEFAULT_AGENT_TUNING,
      llm: { ...DEFAULT_AGENT_TUNING.llm, temperature: 0.3, max_completion_tokens: 140 },
      tts: {
        ...DEFAULT_AGENT_TUNING.tts,
        text_aggregation_mode: "TOKEN",
        rate: "1.1",
        style_degree: "1.2",
      },
      vad: { ...DEFAULT_AGENT_TUNING.vad, start_secs: 0.1 },
    },
  },
];

export function clampAgentTuning(raw: Partial<AgentTuning> | null | undefined): AgentTuning {
  const base = DEFAULT_AGENT_TUNING;
  const llm = { ...base.llm, ...(raw?.llm ?? {}) };
  const tts = { ...base.tts, ...(raw?.tts ?? {}) };
  const stt = { ...base.stt, ...(raw?.stt ?? {}) };
  const vad = { ...base.vad, ...(raw?.vad ?? {}) };
  const turn = { ...base.turn, ...(raw?.turn ?? {}) };
  const interaction = { ...base.interaction, ...(raw?.interaction ?? {}) };

  llm.temperature = Math.min(2, Math.max(0, Number(llm.temperature) || 0));
  llm.top_p = Math.min(1, Math.max(0, Number(llm.top_p) || 0));
  llm.frequency_penalty = Math.min(2, Math.max(-2, Number(llm.frequency_penalty) || 0));
  llm.presence_penalty = Math.min(2, Math.max(-2, Number(llm.presence_penalty) || 0));
  llm.max_completion_tokens = Math.min(800, Math.max(40, Number(llm.max_completion_tokens) || 220));

  const deg = Number(tts.style_degree);
  tts.style_degree = String(Math.min(2, Math.max(0.01, Number.isFinite(deg) ? deg : 1.4)));

  vad.confidence = Math.min(1, Math.max(0.1, Number(vad.confidence) || 0.7));
  vad.start_secs = Math.min(2, Math.max(0.05, Number(vad.start_secs) || 0.15));
  vad.stop_secs = Math.min(2, Math.max(0.2, Number(vad.stop_secs) || 0.2));
  vad.min_volume = Math.min(1, Math.max(0.1, Number(vad.min_volume) || 0.6));

  turn.stop_secs = Math.min(10, Math.max(0.2, Number(turn.stop_secs) || 3));
  turn.pre_speech_ms = Math.min(2000, Math.max(0, Number(turn.pre_speech_ms) || 0));
  turn.max_duration_secs = Math.min(30, Math.max(1, Number(turn.max_duration_secs) || 8));

  if (!["on", "min_words", "locked"].includes(interaction.barge_in)) interaction.barge_in = "on";
  interaction.min_words = Math.min(10, Math.max(1, Number(interaction.min_words) || 3));
  interaction.idle_timeout_secs = Math.min(
    30,
    Math.max(
      0,
      Number(interaction.idle_timeout_secs) || DEFAULT_AGENT_TUNING.interaction.idle_timeout_secs,
    ),
  );
  interaction.mute = (Array.isArray(interaction.mute) ? interaction.mute : []).filter((m) =>
    ["until_first_bot_complete", "during_function_calls"].includes(m),
  );
  interaction.idle_ladder = (
    Array.isArray(interaction.idle_ladder) ? interaction.idle_ladder : []
  ).filter((s) => ["nudge", "direct", "close"].includes(s));

  return { llm, tts, stt, vad, turn, interaction };
}

/** Seed TTS knobs from Prompt Studio VoiceConfig. */
export function tuningFromVoiceConfig(
  voice: {
    voiceId?: string;
    azureVoiceName?: string;
    speed?: number;
    pitch?: number;
    warmth?: number;
    style?: string | null;
  },
  base: AgentTuning = DEFAULT_AGENT_TUNING,
): AgentTuning {
  const warmth = voice.warmth ?? 60;
  let style = voice.style?.trim() || "empathetic";
  let style_degree = "1.4";
  if (!voice.style) {
    if (warmth >= 70) {
      style = "friendly";
      style_degree = "1.6";
    } else if (warmth <= 35) {
      style = "empathetic";
      style_degree = "1.15";
    }
  }
  const speed = voice.speed ?? 1;
  const pitch = voice.pitch ?? 0;
  const rate = String(Math.min(1.25, Math.max(0.85, speed * 1.03)).toFixed(2));
  const pitchStr = pitch === 0 ? "+2%" : `${pitch * 2 >= 0 ? "+" : ""}${pitch * 2}%`;
  const shortName =
    (voice.azureVoiceName || "").trim() ||
    (looksLikeAzureShortName(voice.voiceId) ? voice.voiceId! : base.tts.voice);
  return clampAgentTuning({
    ...base,
    tts: {
      ...base.tts,
      voice: shortName,
      style,
      style_degree,
      rate,
      pitch: pitchStr,
    },
  });
}

function looksLikeAzureShortName(value?: string | null): boolean {
  const v = (value || "").trim();
  if (!v || /\s/.test(v)) return false;
  return /^[a-z]{2,3}-[A-Z]{2}-.+/.test(v) || /Neural|DragonHD|HDFlash|Turbo|MAI-Voice/.test(v);
}

export function tuningFingerprint(t: AgentTuning): string {
  return JSON.stringify(t);
}
