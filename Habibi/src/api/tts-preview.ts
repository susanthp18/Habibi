/**
 * The TTS preview: one utterance synthesised with the voice and tuning on
 * screen, so an author can hear a change before it ships. Carved out of
 * api/prompt-studio, which is versions and deployments.
 */
import { apiPostBlob } from "./config";

export type TtsPreviewInput = {
  text: string;
  voiceId?: string;
  shortName?: string;
  azureVoiceName?: string;
  speed: number;
  pitch: number;
  warmth: number;
  pauseMs: number;
  style?: string | null;
  /** Model-declared controls keyed by provider_models.params_schema. */
  params?: Record<string, unknown>;
  /** Force a new sample instead of replaying the cached take. */
  fresh?: boolean;
};

export type TtsPreviewResult = {
  blob: Blob;
  cacheHit: boolean;
  voiceName: string | null;
  latencyMs: number | null;
};

/** Mock: tiny silent-ish wav so the player pipeline works offline. */
function mockPreviewAudio(): Blob {
  // Minimal valid WAV header + silence (very short).
  const sr = 8000;
  const samples = 800; // 0.1s
  const dataSize = samples * 2;
  const buf = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buf);
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sr, true);
  view.setUint32(28, sr * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);
  return new Blob([buf], { type: "audio/wav" });
}

export async function previewTts(input: TtsPreviewInput): Promise<TtsPreviewResult> {
  const { blob, headers } = await apiPostBlob("/tts/preview", {
    text: input.text,
    voiceId: input.voiceId,
    shortName: input.shortName || input.azureVoiceName,
    azureVoiceName: input.azureVoiceName || input.shortName,
    speed: input.speed,
    pitch: input.pitch,
    warmth: input.warmth,
    pauseMs: input.pauseMs,
    style: input.style || undefined,
    // `params` was declared on TtsPreviewInput and passed by every caller, and
    // then not put in the body — so every model-declared control (temperature,
    // top_p, latency, format, chunk_length, normalize) was collected by the
    // inspector, sent nowhere, and silently replaced by the backend's own
    // defaults. Nine sliders that moved and changed nothing.
    params: input.params ?? {},
    // Take a new sample rather than the stored one. Previews are cached now,
    // so pressing play twice replays the same take; hearing a different one is
    // a deliberate act.
    fresh: input.fresh ?? false,
  });
  const lat = headers.get("X-TTS-Latency-Ms");
  return {
    blob,
    cacheHit: (headers.get("X-TTS-Cache") || "").toUpperCase() === "HIT",
    voiceName: headers.get("X-TTS-Voice"),
    latencyMs: lat ? Number(lat) : null,
  };
}
