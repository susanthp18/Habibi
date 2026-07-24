import { apiUpload, mockDelay, USE_MOCK } from "./config";

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
  const filename = opts?.filename ?? "clip.webm";
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
