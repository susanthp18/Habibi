import { apiGet, apiPost, USE_MOCK, mockDelay } from "./config";
import type { AgentTuning } from "@/data/agent-tuning";

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
  if (USE_MOCK) {
    return mockDelay({ ok: false, webrtcUrl: null, detail: "mock — no voice worker" });
  }
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
  persona?: Record<string, unknown> | null;
  tuning?: AgentTuning | null;
}): Promise<VoiceSandboxStartResponse> {
  if (USE_MOCK) {
    return mockDelay({
      sessionId: `VS-MOCK-${Date.now().toString(36)}`,
      // Use the Vite proxy path (/voice-rtc → runner) rather than hardcoding :7860.
      webrtcUrl: "/voice-rtc/api/offer",
      sandboxRunId: null,
    });
  }
  return apiPost<VoiceSandboxStartResponse>("/voice/sandbox/start", {
    promptVersionId: input.promptVersionId ?? null,
    kbSnapshotId: input.kbSnapshotId ?? null,
    scenarioId: input.scenarioId ?? null,
    persona: input.persona ?? null,
    tuning: input.tuning ?? null,
  });
}

export async function stopVoiceSandbox(sessionId: string): Promise<void> {
  if (USE_MOCK) {
    await mockDelay(null);
    return;
  }
  await apiPost(`/voice/sandbox/${sessionId}/stop`, {});
}

export async function pushVoiceTune(sessionId: string, delta: Partial<AgentTuning>): Promise<void> {
  if (USE_MOCK) {
    await mockDelay(null);
    return;
  }
  await apiPost(`/voice/sandbox/${sessionId}/tune`, { tuning: delta });
}

export async function fetchTuningPresets(): Promise<
  Array<{ id: string; label: string; summary: string; tuning: AgentTuning }>
> {
  if (USE_MOCK) {
    const { AGENT_TUNING_PRESETS } = await import("@/data/agent-tuning");
    return mockDelay(AGENT_TUNING_PRESETS);
  }
  return apiGet<Array<{ id: string; label: string; summary: string; tuning: AgentTuning }>>(
    "/sandbox/tuning/presets",
  );
}
