import { apiUpload, mockDelay, USE_MOCK } from "./config";

function extFromBlobType(type: string): string {
  const map: Record<string, string> = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
  };
  return map[type] ?? "webm";
}

export type SttResult = {
  text: string;
  latencyMs: number;
  language: string;
  recognitionStatus?: string | null;
};

/** Transcribe a short audio clip via Azure Speech STT. Audio is not persisted. */
export async function transcribeAudio(
  blob: Blob,
  opts?: { language?: string; filename?: string },
): Promise<SttResult> {
  const language = opts?.language ?? "en-IN";
  const filename = opts?.filename ?? `clip.${extFromBlobType(blob.type || "audio/webm")}`;
  if (USE_MOCK) {
    return mockDelay({
      text: "I want to know my overdue amount.",
      latencyMs: 120,
      language,
      recognitionStatus: "Success",
    });
  }
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("language", language);
  return apiUpload<SttResult>("/stt/transcribe", form);
}
