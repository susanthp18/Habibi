// -----------------------------------------------------------------------------
// Persona & Prompt Studio — data access seam
//   Reads  (PS-1): versions / presets / voices / deployments
//   Writes (PS-2): draft create/patch, publish, restore-as-draft, rollback
// -----------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  KNOWN_VARIABLES,
  PRESETS,
  TTS_VOICES,
  VERSION_HISTORY,
  type Guardrails,
  type PersonaPreset,
  type PersonaState,
  type PromptVersion,
  type TtsVoice,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import { apiGet, apiPatch, apiPost, apiPostBlob, mockDelay, USE_MOCK } from "./config";
import type { FlowGraph } from "./flow";

export type BotDeployment = {
  id: string;
  botId: string;
  promptVersionId: string;
  kbSnapshotId: string | null;
  ttsVoiceId: string | null;
  environment: "sandbox" | "production";
  status: "active" | "rolled_back" | "retired";
  publishedBy: string | null;
  publishedAt: string | null;
  rollbackDeploymentId: string | null;
  voiceConfig: Record<string, unknown>;
  tuning?: Record<string, unknown>;
};

export type PromptVersionDraftInput = {
  label?: string | null;
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  summary?: string;
  /** Omitted (not sent empty) leaves the stored graph untouched. */
  flow?: FlowGraph;
  botId?: string;
  agentCard?: Record<string, unknown>;
};

export type PromptVersionPatchInput = {
  label?: string | null;
  prompt?: string;
  persona?: PersonaState;
  voice?: VoiceConfig;
  guardrails?: Guardrails;
  summary?: string;
  /** Omitted leaves the stored graph untouched. Explicit `{}` clears it. */
  flow?: FlowGraph;
  /** Omitted leaves the stored card untouched — same key-present rule as flow. */
  agentCard?: Record<string, unknown>;
  /**
   * Not a field — a compile-time barrier.
   *
   * A version belongs to the bot it was created on, and the endpoint's request
   * model forbids extras, so sending `botId` is a 422. Merely leaving it out of
   * this type was not enough: callers build one body for create (which needs
   * `botId`) and reuse it for patch, and TypeScript's excess-property check only
   * fires on object literals, never on a variable. Typing it `never` makes
   * `PromptVersionDraftInput` structurally unassignable here, so the reuse is a
   * type error instead of a runtime 422 that surfaces as "Autosave failed".
   */
  botId?: never;
};

/** Fails the build when its argument is not exactly `true`. */
type Expect<T extends true> = T;

/**
 * Guards the guard: if `botId?: never` is ever dropped from the patch type, a
 * draft body becomes assignable again and this line stops compiling. Type-only,
 * so it emits nothing.
 */
type _DraftBodyIsNotPatchable = Expect<
  PromptVersionDraftInput extends PromptVersionPatchInput ? false : true
>;

/**
 * Project a draft body onto the fields PATCH accepts.
 *
 * An explicit allowlist rather than `{...rest}`: a field added to
 * `PromptVersionDraftInput` later must be considered here before it can reach
 * the endpoint, instead of silently riding along and 422-ing.
 */
export function toPatchInput(body: PromptVersionDraftInput): PromptVersionPatchInput {
  const patch: PromptVersionPatchInput = {
    label: body.label,
    prompt: body.prompt,
    persona: body.persona,
    voice: body.voice,
    guardrails: body.guardrails,
  };
  if (body.summary !== undefined) patch.summary = body.summary;
  if (body.flow) patch.flow = body.flow;
  if (body.agentCard) patch.agentCard = body.agentCard;
  return patch;
}

type TtsVoiceApi = TtsVoice & { azureVoiceName?: string | null };

const VERSIONS_KEY = ["prompt-versions"] as const;
const PUBLISHED_KEY = ["prompt-versions", "published"] as const;
const DEPLOYMENTS_KEY = ["bot-deployments"] as const;

function invalidatePromptStudio(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: VERSIONS_KEY });
  void qc.invalidateQueries({ queryKey: PUBLISHED_KEY });
  void qc.invalidateQueries({ queryKey: DEPLOYMENTS_KEY });
}

let _mockVersions: PromptVersion[] = VERSION_HISTORY.map((v) => ({
  ...v,
  persona: { ...v.persona, traits: { ...v.persona.traits }, fallbackLanguages: [...v.persona.fallbackLanguages] },
  voice: { ...v.voice },
  guardrails: { ...v.guardrails, prohibited: [...v.guardrails.prohibited] },
}));

function _mockClone(v: PromptVersion): PromptVersion {
  return {
    ...v,
    persona: { ...v.persona, traits: { ...v.persona.traits }, fallbackLanguages: [...v.persona.fallbackLanguages] },
    voice: { ...v.voice },
    guardrails: { ...v.guardrails, prohibited: [...v.guardrails.prohibited] },
    flow: v.flow ? { ...v.flow, nodes: [...v.flow.nodes], edges: [...v.flow.edges] } : v.flow,
  };
}

// ---------- reads ----------

export async function fetchPromptVersions(botId?: string): Promise<PromptVersion[]> {
  if (USE_MOCK) return mockDelay(_mockVersions.map(_mockClone));
  const q = botId ? `?botId=${encodeURIComponent(botId)}` : "";
  return apiGet<PromptVersion[]>(`/prompt-versions${q}`);
}

export async function fetchPublishedPromptVersion(botId?: string): Promise<PromptVersion | null> {
  if (USE_MOCK) {
    return mockDelay(
      _mockClone(
        _mockVersions.find((v) => v.status === "published") ?? _mockVersions[0] ?? VERSION_HISTORY[0],
      ),
    );
  }
  try {
    const q = botId ? `?botId=${encodeURIComponent(botId)}` : "";
    return await apiGet<PromptVersion>(`/prompt-versions/published${q}`);
  } catch {
    return null;
  }
}

export async function fetchPersonaPresets(): Promise<PersonaPreset[]> {
  if (USE_MOCK) return mockDelay(PRESETS);
  return apiGet<PersonaPreset[]>("/persona-presets");
}

export async function fetchTtsVoices(): Promise<TtsVoice[]> {
  if (USE_MOCK) return mockDelay(TTS_VOICES);
  const rows = await apiGet<TtsVoiceApi[]>("/tts-voices");
  return rows.map(({ id, name, gender, accent, duration }) => ({
    id,
    name,
    gender,
    accent,
    duration,
  }));
}

export type TtsCatalogVoice = {
  shortName: string;
  displayName: string;
  localName: string;
  gender: string;
  locale: string;
  localeName: string;
  voiceType: string;
  status: string;
  priceTier: string;
  isPremium: boolean;
  approxUsdPer1MChars: number | null;
  styles: string[];
  personalities: string[];
  scenarios: string[];
  wordsPerMinute: number | null;
  sampleRateHertz: number | null;
  modelSeries: string[];
  removedAt?: string | null;
  enabledForPicker?: boolean;
  raw?: Record<string, unknown> | null;
};

export type TtsCatalogList = {
  items: TtsCatalogVoice[];
  total: number;
  nextCursor: string | null;
  lastSyncedAt: string | null;
  defaultVoice: string;
  premiumHiddenByDefault: boolean;
};

export type TtsCatalogQuery = {
  q?: string;
  locale?: string;
  gender?: string;
  status?: string;
  priceTier?: string;
  includePremium?: boolean;
  includeRemoved?: boolean;
  limit?: number;
  cursor?: string;
};

export type TtsPriceTier = {
  tier: string;
  label: string;
  approxUsdPer1MChars: number | null;
  isPremium: boolean;
  notes: string;
};

export type TtsSyncRun = {
  id: string;
  source?: string | null;
  fetchedCount: number;
  upserted: number;
  softRemoved: number;
  unchanged: number;
  error?: string | null;
  region?: string;
  defaultVoice?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
};

export type TtsVoiceWarning = {
  shortName: string;
  code: string;
  message: string;
  fallbackVoice: string;
};

export async function fetchTtsVoiceCatalog(params: TtsCatalogQuery = {}): Promise<TtsCatalogList> {
  if (USE_MOCK) {
    return mockDelay({
      items: TTS_VOICES.map((v) => ({
        shortName: `en-IN-${v.name}Neural`,
        displayName: v.name,
        localName: v.name,
        gender: v.gender,
        locale: "en-IN",
        localeName: "English (India)",
        voiceType: "Neural",
        status: "GA",
        priceTier: "standard",
        isPremium: false,
        approxUsdPer1MChars: 15,
        styles: [],
        personalities: [],
        scenarios: [],
        wordsPerMinute: null,
        sampleRateHertz: 48000,
        modelSeries: ["Monolingual"],
      })),
      total: TTS_VOICES.length,
      nextCursor: null,
      lastSyncedAt: new Date().toISOString(),
      defaultVoice: "en-IN-AartiNeural",
      premiumHiddenByDefault: true,
    });
  }
  const q = new URLSearchParams();
  if (params.q) q.set("q", params.q);
  if (params.locale) q.set("locale", params.locale);
  if (params.gender) q.set("gender", params.gender);
  if (params.status) q.set("status", params.status);
  if (params.priceTier) q.set("price_tier", params.priceTier);
  if (params.includePremium) q.set("include_premium", "true");
  if (params.includeRemoved) q.set("include_removed", "true");
  if (params.limit) q.set("limit", String(params.limit));
  if (params.cursor) q.set("cursor", params.cursor);
  const qs = q.toString();
  return apiGet<TtsCatalogList>(`/tts-voices/catalog${qs ? `?${qs}` : ""}`);
}

export async function fetchTtsVoiceDetail(shortName: string): Promise<TtsCatalogVoice> {
  if (USE_MOCK) {
    const catalog = await fetchTtsVoiceCatalog();
    const found = catalog.items.find((v) => v.shortName === shortName);
    if (!found) throw new Error(`tts_voice_not_found: ${shortName}`);
    return mockDelay(found);
  }
  return apiGet<TtsCatalogVoice>(`/tts-voices/catalog/${encodeURIComponent(shortName)}`);
}

export async function fetchTtsPricing(): Promise<TtsPriceTier[]> {
  if (USE_MOCK) {
    return mockDelay([
      { tier: "standard", label: "Standard Neural", approxUsdPer1MChars: 15, isPremium: false, notes: "" },
      { tier: "hd", label: "Neural HD", approxUsdPer1MChars: 22, isPremium: true, notes: "" },
    ]);
  }
  return apiGet<TtsPriceTier[]>("/tts-voices/pricing");
}

export async function syncTtsVoiceCatalog(): Promise<TtsSyncRun> {
  if (USE_MOCK) {
    return mockDelay({
      id: `sync-mock-${Date.now()}`,
      source: "mock",
      fetchedCount: TTS_VOICES.length,
      upserted: TTS_VOICES.length,
      softRemoved: 0,
      unchanged: 0,
      region: "centralindia",
      defaultVoice: "en-IN-AartiNeural",
    });
  }
  return apiPost<TtsSyncRun>("/tts-voices/catalog/sync", {});
}

export async function fetchTtsSyncRuns(limit = 20): Promise<TtsSyncRun[]> {
  if (USE_MOCK) {
    return mockDelay([
      {
        id: "sync-mock-1",
        source: "mock",
        fetchedCount: TTS_VOICES.length,
        upserted: TTS_VOICES.length,
        softRemoved: 0,
        unchanged: 0,
        region: "centralindia",
        startedAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
      },
    ]);
  }
  return apiGet<TtsSyncRun[]>(`/tts-voices/catalog/sync-runs?limit=${limit}`);
}

export async function fetchTtsVoiceWarning(shortName: string): Promise<TtsVoiceWarning | null> {
  if (USE_MOCK) return mockDelay(null);
  return apiGet<TtsVoiceWarning | null>(
    `/tts-voices/catalog-warning?shortName=${encodeURIComponent(shortName)}`,
  );
}

export function useTtsVoiceCatalog(params: TtsCatalogQuery) {
  return useQuery({
    queryKey: ["tts-voice-catalog", params],
    queryFn: () => fetchTtsVoiceCatalog(params),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}

/** Infinite catalog pages — VoicePanel / Tuning Studio primary loader. */
export function useInfiniteTtsVoiceCatalog(
  params: Omit<TtsCatalogQuery, "cursor"> & { limit?: number },
) {
  const limit = params.limit ?? 50;
  const { limit: _ignored, ...filters } = params;
  return useInfiniteQuery({
    queryKey: ["tts-voice-catalog-infinite", filters, limit],
    queryFn: ({ pageParam }) =>
      fetchTtsVoiceCatalog({
        ...filters,
        limit,
        cursor: pageParam ?? undefined,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    staleTime: 30_000,
  });
}

export function useTtsSyncRuns(limit = 5) {
  return useQuery({
    queryKey: ["tts-voice-sync-runs", limit],
    queryFn: () => fetchTtsSyncRuns(limit),
    staleTime: 30_000,
  });
}

export function useTtsPricing() {
  return useQuery({
    queryKey: ["tts-voice-pricing"],
    queryFn: fetchTtsPricing,
    staleTime: 300_000,
  });
}

export async function fetchBotDeployments(params?: {
  environment?: "sandbox" | "production";
  status?: "active" | "rolled_back" | "retired";
  botId?: string;
}): Promise<BotDeployment[]> {
  if (USE_MOCK) {
    const published = VERSION_HISTORY.find((v) => v.status === "published") ?? VERSION_HISTORY[0];
    return mockDelay([
      {
        id: "DEP-2026-07-PROD",
        botId: "kaia-v2-4",
        promptVersionId: published?.id ?? "v1_4",
        kbSnapshotId: "kb-snapshot-2026-07",
        ttsVoiceId: published?.voice.azureVoiceName
          ?? published?.voice.voiceId
          ?? "en-IN-AartiNeural",
        environment: "production" as const,
        status: "active" as const,
        publishedBy: "Priya Nair",
        publishedAt: "2026-07-21T08:30:00Z",
        rollbackDeploymentId: null,
        voiceConfig: {},
      },
    ]);
  }
  const q = new URLSearchParams();
  if (params?.environment) q.set("environment", params.environment);
  if (params?.status) q.set("status", params.status);
  if (params?.botId) q.set("botId", params.botId);
  const qs = q.toString();
  return apiGet<BotDeployment[]>(`/bot-deployments${qs ? `?${qs}` : ""}`);
}

export function usePromptVersions(botId?: string) {
  return useQuery({
    queryKey: [...VERSIONS_KEY, botId ?? "all"],
    queryFn: () => fetchPromptVersions(botId),
    staleTime: 15_000,
  });
}

export function usePublishedPromptVersion(botId?: string) {
  return useQuery({
    queryKey: [...PUBLISHED_KEY, botId ?? "default"],
    queryFn: () => fetchPublishedPromptVersion(botId),
    staleTime: 15_000,
  });
}

export function usePersonaPresets() {
  return useQuery({
    queryKey: ["persona-presets"],
    queryFn: fetchPersonaPresets,
    staleTime: 60_000,
  });
}

export function useTtsVoices() {
  return useQuery({
    queryKey: ["tts-voices"],
    queryFn: fetchTtsVoices,
    staleTime: 60_000,
  });
}

export type PromptTokenEstimate = {
  tokens: number;
  encoding: string;
  usdPer1M: number;
  costUsd: number;
  source: "tiktoken" | "heuristic";
};

export async function estimatePromptTokens(prompt: string): Promise<PromptTokenEstimate> {
  if (USE_MOCK) {
    const tokens = Math.ceil((prompt || "").length / 4);
    const usdPer1M = 2.5;
    return mockDelay({
      tokens,
      encoding: "heuristic",
      usdPer1M,
      costUsd: Math.round((tokens * usdPer1M) / 1_000_000 * 1_000_000) / 1_000_000,
      source: "heuristic",
    });
  }
  return apiPost<PromptTokenEstimate>("/prompt-versions/estimate-tokens", { prompt });
}

/** Debounced tiktoken estimate for the Prompt Studio editor footer. */
export function usePromptTokenEstimate(prompt: string) {
  const [debounced, setDebounced] = useState(prompt);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(prompt), 250);
    return () => window.clearTimeout(t);
  }, [prompt]);

  return useQuery({
    queryKey: ["prompt-studio", "token-estimate", debounced],
    queryFn: () => estimatePromptTokens(debounced),
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  });
}

// ---------- writes ----------

export async function createPromptVersion(input: PromptVersionDraftInput): Promise<PromptVersion> {
  if (USE_MOCK) {
    const label = input.label?.trim() || null;
    const id = (label ?? "draft").replace(/\./g, "_") + `-${Date.now().toString(36).slice(-4)}`;
    const created: PromptVersion = {
      id,
      label: label ?? id,
      author: "You",
      status: "draft",
      createdAt: new Date().toISOString(),
      summary: input.summary ?? "",
      prompt: input.prompt,
      persona: input.persona,
      voice: input.voice,
      guardrails: input.guardrails,
      flow: input.flow,
    };
    _mockVersions = [created, ..._mockVersions];
    return mockDelay(_mockClone(created));
  }
  return apiPost<PromptVersion>("/prompt-versions", input);
}

export async function patchPromptVersion(
  versionId: string,
  input: PromptVersionPatchInput,
): Promise<PromptVersion> {
  if (USE_MOCK) {
    const idx = _mockVersions.findIndex((v) => v.id === versionId);
    if (idx < 0) throw new Error(`prompt_version_not_found: ${versionId}`);
    if (_mockVersions[idx].status !== "draft") throw new Error("prompt_version_not_draft");
    const next = {
      ..._mockVersions[idx],
      ...(input.label !== undefined ? { label: input.label ?? _mockVersions[idx].label } : {}),
      ...(input.prompt !== undefined ? { prompt: input.prompt } : {}),
      ...(input.persona !== undefined ? { persona: input.persona } : {}),
      ...(input.voice !== undefined ? { voice: input.voice } : {}),
      ...(input.guardrails !== undefined ? { guardrails: input.guardrails } : {}),
      ...(input.summary !== undefined ? { summary: input.summary } : {}),
      ...(input.flow !== undefined ? { flow: input.flow } : {}),
      ...(input.agentCard !== undefined ? { agentCard: input.agentCard } : {}),
    };
    _mockVersions = _mockVersions.map((v, i) => (i === idx ? next : v));
    return mockDelay(_mockClone(next));
  }
  return apiPatch<PromptVersion>(`/prompt-versions/${versionId}`, input);
}

export async function publishPromptVersion(
  versionId: string,
  summary = "",
  opts?: {
    kbSnapshotId?: string | null;
    tuning?: unknown;
    trafficPct?: number | null;
    shadow?: boolean;
    autoRollback?: string[] | null;
  },
): Promise<PromptVersion> {
  if (USE_MOCK) {
    const idx = _mockVersions.findIndex((v) => v.id === versionId);
    if (idx < 0) throw new Error(`prompt_version_not_found: ${versionId}`);
    if (_mockVersions[idx].status !== "draft") throw new Error("prompt_version_not_draft");
    _mockVersions = _mockVersions.map((v, i) => {
      if (i === idx) {
        return {
          ...v,
          status: "published" as const,
          summary: summary.trim() || v.summary,
        };
      }
      if (v.status === "published") return { ...v, status: "archived" as const };
      return v;
    });
    return mockDelay(_mockClone(_mockVersions[idx]));
  }
  return apiPost<PromptVersion>(`/prompt-versions/${versionId}/publish`, {
    summary,
    kbSnapshotId: opts?.kbSnapshotId ?? null,
    tuning: opts?.tuning ?? null,
    trafficPct: opts?.trafficPct ?? null,
    shadow: opts?.shadow ?? false,
    autoRollback: opts?.autoRollback ?? null,
  });
}

export async function restorePromptVersionAsDraft(versionId: string): Promise<PromptVersion> {
  if (USE_MOCK) {
    const source = _mockVersions.find((v) => v.id === versionId);
    if (!source) throw new Error(`prompt_version_not_found: ${versionId}`);
    const created: PromptVersion = {
      ..._mockClone(source),
      id: `${source.id}-r-${Date.now().toString(36).slice(-4)}`,
      label: source.label,
      author: "You",
      status: "draft",
      createdAt: new Date().toISOString(),
      summary: `restored from ${source.label}`,
    };
    _mockVersions = [created, ..._mockVersions];
    return mockDelay(_mockClone(created));
  }
  return apiPost<PromptVersion>(`/prompt-versions/${versionId}/restore-as-draft`, {});
}

export async function rollbackBotDeployment(deploymentId: string): Promise<BotDeployment> {
  if (USE_MOCK) {
    // Simulate rollback: re-publish the prompt tied to the target deployment id.
    const published = _mockVersions.find((v) => v.status === "published");
    const archived = _mockVersions.find((v) => v.status === "archived") ?? _mockVersions[1];
    if (!archived) throw new Error("no_prior_deployment");
    _mockVersions = _mockVersions.map((v) => {
      if (v.id === archived.id) return { ...v, status: "published" as const };
      if (v.status === "published") return { ...v, status: "archived" as const };
      return v;
    });
    return mockDelay({
      id: `DEP-RB-${Date.now().toString(36).slice(-4)}`,
      botId: "kaia-v2-4",
      promptVersionId: archived.id,
      kbSnapshotId: "kb-snapshot-2026-07",
      ttsVoiceId:
        archived.voice.azureVoiceName ?? archived.voice.voiceId ?? "en-IN-AartiNeural",
      environment: "production",
      status: "active",
      publishedBy: "You",
      publishedAt: new Date().toISOString(),
      rollbackDeploymentId: published?.id ? "DEP-2026-07-PROD" : null,
      voiceConfig: {},
    });
  }
  return apiPost<BotDeployment>(`/bot-deployments/${deploymentId}/rollback`, {});
}

export async function discardPromptVersion(versionId: string): Promise<PromptVersion> {
  if (USE_MOCK) {
    const idx = _mockVersions.findIndex((v) => v.id === versionId);
    if (idx < 0) throw new Error(`prompt_version_not_found: ${versionId}`);
    if (_mockVersions[idx].status !== "draft") throw new Error("prompt_version_not_draft");
    _mockVersions = _mockVersions.map((v, i) =>
      i === idx ? { ...v, status: "archived" as const } : v,
    );
    return mockDelay(_mockClone(_mockVersions[idx]));
  }
  return apiPost<PromptVersion>(`/prompt-versions/${versionId}/discard`, {});
}

export type PromptLintFinding = {
  severity: "error" | "warn" | "info";
  code: string;
  message: string;
  span?: { start: number; end: number } | null;
};

export async function lintPromptVersion(input: {
  prompt: string;
  guardrails: Guardrails;
  includeLlm?: boolean;
}): Promise<PromptLintFinding[]> {
  if (USE_MOCK) {
    const findings: PromptLintFinding[] = [];
    const unknown = Array.from(input.prompt.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g))
      .map((m) => m[1])
      .filter((v) => !KNOWN_VARIABLES.includes(v as (typeof KNOWN_VARIABLES)[number]));
    for (const v of Array.from(new Set(unknown))) {
      findings.push({
        severity: "warn",
        code: "unknown_variable",
        message: `Unknown variable {${v}} — will not be substituted at runtime.`,
      });
    }
    if (input.guardrails.alwaysDiscloseRecording && !/record/i.test(input.prompt)) {
      findings.push({
        severity: "error",
        code: "missing_recording_disclosure",
        message: "Guardrail alwaysDiscloseRecording is on, but the prompt has no recording-disclosure language.",
      });
    }
    for (const w of input.guardrails.prohibited || []) {
      if (w && input.prompt.toLowerCase().includes(w.toLowerCase())) {
        findings.push({
          severity: "error",
          code: "prohibited_word_in_prompt",
          message: `Prohibited phrase "${w}" appears in the system prompt.`,
        });
      }
    }
    return mockDelay(findings);
  }
  const res = await apiPost<{ findings: PromptLintFinding[] }>("/prompt-versions/lint", {
    prompt: input.prompt,
    guardrails: input.guardrails,
    includeLlm: Boolean(input.includeLlm),
  });
  return res.findings;
}

export function useDiscardPromptVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: discardPromptVersion,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useRollbackBotDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: rollbackBotDeployment,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useLintPrompt() {
  return useMutation({
    mutationFn: lintPromptVersion,
  });
}

export async function fetchActiveBotDeployment(
  environment: "production" | "sandbox" = "production",
  botId?: string,
): Promise<BotDeployment | null> {
  if (USE_MOCK) {
    const rows = await fetchBotDeployments({ environment, status: "active", botId });
    return rows[0] ?? null;
  }
  try {
    const q = new URLSearchParams({ environment });
    if (botId) q.set("botId", botId);
    return await apiGet<BotDeployment>(`/bot-deployments/active?${q.toString()}`);
  } catch {
    return null;
  }
}

export function useActiveProdDeployment(botId?: string) {
  return useQuery({
    queryKey: [...DEPLOYMENTS_KEY, "active", "production", botId ?? "default"],
    queryFn: () => fetchActiveBotDeployment("production", botId),
    staleTime: 15_000,
  });
}

export function useProdDeployments(botId?: string) {
  return useQuery({
    queryKey: [...DEPLOYMENTS_KEY, "production", botId ?? "all"],
    queryFn: () => fetchBotDeployments({ environment: "production", botId }),
    staleTime: 15_000,
  });
}

/** True when PATCH draft is expected to fail and caller should create a new draft instead. */
function isDraftPatchFallbackError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const msg = err.message.toLowerCase();
  return (
    msg.includes("404") ||
    msg.includes("409") ||
    msg.includes("not found") ||
    msg.includes("prompt_version_not_found") ||
    msg.includes("prompt_version_not_draft") ||
    msg.includes("not_draft") ||
    msg.includes("not-draft")
  );
}

/** Create-or-patch a draft from editor state, then publish it. */
export async function publishStudioDraft(opts: {
  draftId?: string | null;
  label: string;
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  summary: string;
  flow?: FlowGraph;
  agentCard?: Record<string, unknown>;
  botId?: string;
  trafficPct?: number;
  shadow?: boolean;
  autoRollback?: string[];
}): Promise<PromptVersion> {
  const body: PromptVersionDraftInput = {
    label: opts.label,
    prompt: opts.prompt,
    persona: opts.persona,
    voice: opts.voice,
    guardrails: opts.guardrails,
    botId: opts.botId,
  };
  if (opts.flow) body.flow = opts.flow;
  // Sent explicitly rather than left to the draft: publish may have to create
  // the version from scratch (draftId null after a discard or a card-only
  // edit), and a version created without the card ships an empty one.
  if (opts.agentCard) body.agentCard = opts.agentCard;
  let draftId = opts.draftId ?? null;
  if (draftId) {
    try {
      await patchPromptVersion(draftId, toPatchInput(body));
    } catch (err) {
      if (!isDraftPatchFallbackError(err)) throw err;
      // Draft may have been published/archived elsewhere — fall through to create.
      draftId = null;
    }
  }
  if (!draftId) {
    const created = await createPromptVersion(body);
    draftId = created.id;
  }
  return publishPromptVersion(draftId, opts.summary, {
    trafficPct: opts.trafficPct,
    shadow: opts.shadow,
    autoRollback: opts.autoRollback,
  });
}

/** Ensure a draft exists for Sandbox try-out / autosave of editor state. */
export async function ensureStudioDraft(opts: {
  draftId?: string | null;
  label: string;
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  flow?: FlowGraph;
  agentCard?: Record<string, unknown>;
  summary?: string;
  botId?: string;
}): Promise<PromptVersion> {
  const body: PromptVersionDraftInput = {
    label: opts.label,
    prompt: opts.prompt,
    persona: opts.persona,
    voice: opts.voice,
    guardrails: opts.guardrails,
    summary: opts.summary ?? "draft autosave",
    botId: opts.botId,
  };
  // Omitted rather than sent empty: the backend leaves the column untouched
  // when the key is absent, so a save issued before the flow tab ever loaded
  // cannot wipe an authored graph. Same rule for the card.
  if (opts.flow) body.flow = opts.flow;
  if (opts.agentCard) body.agentCard = opts.agentCard;
  if (opts.draftId) {
    try {
      return await patchPromptVersion(opts.draftId, toPatchInput(body));
    } catch (err) {
      if (!isDraftPatchFallbackError(err)) throw err;
      /* create below */
    }
  }
  return createPromptVersion(body);
}

export function usePublishStudioDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: publishStudioDraft,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useRestorePromptVersionAsDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => restorePromptVersionAsDraft(versionId),
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useEnsureStudioDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ensureStudioDraft,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

// ---------- TTS preview (PS-4) ----------

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
  if (USE_MOCK) {
    await mockDelay(null, 200);
    return { blob: mockPreviewAudio(), cacheHit: true, voiceName: "mock", latencyMs: 200 };
  }
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
  });
  const lat = headers.get("X-TTS-Latency-Ms");
  return {
    blob,
    cacheHit: (headers.get("X-TTS-Cache") || "").toUpperCase() === "HIT",
    voiceName: headers.get("X-TTS-Voice"),
    latencyMs: lat ? Number(lat) : null,
  };
}
