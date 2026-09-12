import { apiGet, apiPost } from "./config";
import type { AgentTuning, AgentTuningPreset } from "@/api/types/agent-tuning";
import type { Persona } from "@/api/types/sandbox";

export type VoiceStatus = {
  ok: boolean;
  webrtcUrl: string | null;
  detail?: string | null;
};

export type VoiceSandboxStartResponse = {
  sessionId: string;
  webrtcUrl: string;
  sandboxRunId: string | null;
};

export async function fetchVoiceStatus(): Promise<VoiceStatus> {
  try {
    return await apiGet<VoiceStatus>("/voice/status");
  } catch {
    return { ok: false, webrtcUrl: null, detail: "voice worker unreachable" };
  }
}

export async function startVoiceSandbox(input: {
  promptVersionId?: string | null;
  kbSnapshotId?: string | null;
  scenarioId?: string | null;
  persona?: Persona | null;
  tuning?: AgentTuning | null;
}): Promise<VoiceSandboxStartResponse> {
  return apiPost<VoiceSandboxStartResponse>("/voice/sandbox/start", {
    promptVersionId: input.promptVersionId ?? null,
    kbSnapshotId: input.kbSnapshotId ?? null,
    scenarioId: input.scenarioId ?? null,
    persona: input.persona ?? null,
    tuning: input.tuning ?? null,
  });
}

export async function stopVoiceSandbox(sessionId: string): Promise<void> {
  await apiPost(`/voice/sandbox/${sessionId}/stop`, {});
}

export async function pushVoiceTune(sessionId: string, delta: Partial<AgentTuning>): Promise<void> {
  await apiPost(`/voice/sandbox/${sessionId}/tune`, { tuning: delta });
}

export async function fetchTuningPresets(): Promise<AgentTuningPreset[]> {
  return apiGet<AgentTuningPreset[]>("/sandbox/tuning/presets");
}
