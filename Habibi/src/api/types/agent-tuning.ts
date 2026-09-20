/**
 * Wire / domain types for agent tuning: one struct for Sandbox Studio,
 * voice.bot and the Promote bundle.
 *
 * Lived in `lib/agent-tuning.ts` beside the defaults and the clamp; moved
 * here so `api/voice-sandbox.ts` does not take its contract from a fixture
 * module (WP-048).
 */

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
export type MuteStrategyId =
  | "until_first_bot_complete"
  | "during_function_calls"
  | "always"
  | "first_speech";
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

/**
 * Served by `GET /sandbox/tuning/presets` (`agent_core.tuning.PRESETS`). The
 * browser held its own four and they had drifted — `idle_timeout_secs` 5 vs
 * the server's 10, `style` "empathetic" vs "serious" — so the sandbox showed
 * a preset the call never ran under.
 */
export type AgentTuningPreset = {
  id: string;
  label: string;
  tuning: AgentTuning;
};
