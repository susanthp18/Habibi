// -----------------------------------------------------------------------------
// Provider registry — data access seam for Agent Studio → Providers.
//
// The catalog was single-vendor until now, so the picker could assume every
// voice was an Azure voice. These types are what let one screen show many.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDelete, apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

export type ProviderSlot = "stt" | "tts" | "llm";

export type ProviderModel = {
  id: string;
  providerId: string;
  providerName: string;
  kind: ProviderSlot;
  modelId: string;
  displayName: string;
  serviceClass: string;
  locales: string[];
  streaming: boolean;
  /** True only for models that follow a language change *inside* one sentence. */
  codeSwitch: boolean;
  onPrem: boolean;
  diarization: boolean;
  styles: string[];
  costPerUnit: number | null;
  costUnit: string | null;
  /** null until one of our own shadow runs measures it. Never a vendor number. */
  measuredLatencyP50Ms: number | null;
  measuredLatencyP95Ms: number | null;
  notes: string;
  /** Controls this model actually honours, rendered generically by the
   *  inspector. Empty means "not mapped" — show nothing rather than another
   *  provider's knobs. */
  paramsSchema: Array<Record<string, unknown>>;
  enabled: boolean;
  /** false when no API key is present — shown greyed, never hidden. */
  configured: boolean;
  /**
   * Whether the model can actually run on a call. A key makes a provider
   * *configured*; it does not make the model *runnable*, and the two fail
   * differently — a missing key is fixable from the Integrations screen, a
   * service class that does not import is not. Binding a non-live model used
   * to fall back to Azure silently.
   */
  runtime: "live" | "preview_only" | "unavailable";
  /** Why, when `runtime` is not "live". Shown as the tooltip. */
  runtimeDetail: string;
  /**
   * True when the vendor's engine samples, so two identical requests give two
   * different performances — different pacing and emphasis, not encoder noise.
   *
   * Measured spread over three identical calls: Azure 0%, Cartesia 6%, Fish
   * 23%, Deepgram 39%. Previews are cached so comparison works at all; this
   * flag is what decides whether offering "new take" would mean anything, so a
   * deterministic engine gets no such button instead of an inert one.
   */
  sampling: boolean;
};

export type ProviderBinding = {
  id: string;
  botId: string | null;
  slot: ProviderSlot;
  locale: string | null;
  providerModelId: string;
  providerId: string;
  providerName: string;
  modelId: string;
  displayName: string;
  voiceRef: string | null;
  priority: number;
  settings: Record<string, unknown>;
  enabled: boolean;
};

export type ProviderBindingInput = {
  slot: ProviderSlot;
  providerModelId: string;
  botId?: string | null;
  locale?: string | null;
  voiceRef?: string | null;
  priority?: number;
  settings?: Record<string, unknown>;
  enabled?: boolean;
};

export type ProviderPoolKey = {
  tail: string;
  uses: number;
  retired: boolean;
  lastError: string;
};

export type ProviderPool = {
  provider: string;
  total: number;
  available: number;
  retired: number;
  sessionsBound: number;
  keys: ProviderPoolKey[];
};

export type VoiceProviderCount = { providerId: string; count: number };

/** Voice counts per provider for the catalog filter chips. Separate from the
 *  paginated list because a chip must count the whole catalog, not one page. */
export function useVoiceProviderCounts() {
  return useQuery({
    queryKey: ["tts-voice-provider-counts"],
    queryFn: () => apiGet<VoiceProviderCount[]>("/tts-voices/catalog-provider-counts"),
    staleTime: 60_000,
  });
}

export type VoiceLocaleCount = { locale: string; localeName: string; count: number };

/** Locales actually present in the catalog, most-voices-first.
 *  Replaces a hardcoded India-only preset list that hid 143 of 150 locales. */
export function useVoiceLocaleCounts(limit = 200) {
  return useQuery({
    queryKey: ["tts-voice-locale-counts", limit],
    queryFn: () => apiGet<VoiceLocaleCount[]>(`/tts-voices/catalog-locale-counts?limit=${limit}`),
    staleTime: 60_000,
  });
}

export function useProviderModels(kind?: ProviderSlot) {
  return useQuery({
    queryKey: ["provider-models", kind ?? "all"],
    queryFn: () => apiGet<ProviderModel[]>(`/providers/models${kind ? `?kind=${kind}` : ""}`),
    staleTime: 5 * 60_000,
  });
}

// ---------------------------------------------------------------------------
// Bindings and key pools
//
// Mock fixtures are deliberately unremarkable. A mock pool showing every key
// healthy would make the strip look like it was reporting something it is not,
// so the fixture carries one exhausted key — the state the strip exists to
// catch — alongside a healthy pool.
// ---------------------------------------------------------------------------

const MOCK_POOLS: ProviderPool[] = [
  {
    provider: "azure",
    total: 2,
    available: 2,
    retired: 0,
    sessionsBound: 1,
    keys: [
      { tail: "9f2a", uses: 118, retired: false, lastError: "" },
      { tail: "c410", uses: 96, retired: false, lastError: "" },
    ],
  },
  {
    provider: "fish",
    total: 2,
    available: 1,
    retired: 1,
    sessionsBound: 0,
    keys: [
      { tail: "1b77", uses: 240, retired: true, lastError: "402 free tier exhausted" },
      { tail: "8de3", uses: 12, retired: false, lastError: "" },
    ],
  },
];

const MOCK_BINDINGS: ProviderBinding[] = [
  {
    id: "APB-mock-tts",
    botId: null,
    slot: "tts",
    locale: "en-IN",
    providerModelId: "PM-azure-neural",
    providerId: "azure",
    providerName: "Azure",
    modelId: "azure-neural",
    displayName: "Azure neural",
    voiceRef: "en-IN-NeerjaNeural",
    priority: 100,
    settings: {},
    enabled: true,
  },
  {
    id: "APB-mock-stt",
    botId: "kaia-v2-4",
    slot: "stt",
    locale: null,
    providerModelId: "PM-deepgram-nova",
    providerId: "deepgram",
    providerName: "Deepgram",
    modelId: "nova-3",
    displayName: "Nova 3",
    voiceRef: null,
    priority: 50,
    settings: {},
    enabled: true,
  },
];

export async function fetchProviderBindings(botId?: string | null): Promise<ProviderBinding[]> {
  if (USE_MOCK) {
    return mockDelay(botId ? MOCK_BINDINGS : MOCK_BINDINGS.filter((b) => b.botId === null));
  }
  return apiGet<ProviderBinding[]>(
    `/providers/bindings${botId ? `?botId=${encodeURIComponent(botId)}` : ""}`,
  );
}

/**
 * Bindings for a bot **plus the tenant defaults it inherits** — the server
 * returns both (`bot_id IS NULL OR bot_id = :bot`). A row with `botId === null`
 * is inherited, and deleting it affects every bot, so the two must not be
 * rendered as if they were the same thing.
 */
export function useProviderBindings(botId?: string | null) {
  return useQuery({
    queryKey: ["provider-bindings", botId ?? "tenant"],
    queryFn: () => fetchProviderBindings(botId),
  });
}

export async function fetchProviderPools(): Promise<ProviderPool[]> {
  if (USE_MOCK) return mockDelay(MOCK_POOLS);
  return apiGet<ProviderPool[]>("/providers/pools");
}

/** Key-pool health. Polled, because free-tier exhaustion is the failure the
 *  operator needs to see *before* a demo call hits it, not after. */
export function useProviderPools(enabled = true) {
  return useQuery({
    queryKey: ["provider-pools"],
    queryFn: fetchProviderPools,
    refetchInterval: enabled ? 30_000 : false,
    enabled,
  });
}

export async function upsertBinding(input: ProviderBindingInput): Promise<ProviderBinding> {
  if (USE_MOCK) {
    return mockDelay({
      id: `APB-mock-${input.slot}-${input.priority ?? 100}`,
      botId: input.botId ?? null,
      slot: input.slot,
      locale: input.locale ?? null,
      providerModelId: input.providerModelId,
      providerId: "mock",
      providerName: "Mock provider",
      modelId: input.providerModelId,
      displayName: input.providerModelId,
      voiceRef: input.voiceRef ?? null,
      priority: input.priority ?? 100,
      settings: input.settings ?? {},
      enabled: input.enabled ?? true,
    });
  }
  return apiPost<ProviderBinding>("/providers/bindings", input);
}

export function useUpsertBinding(botId?: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: upsertBinding,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["provider-bindings", botId ?? "tenant"] });
    },
  });
}

export async function deleteBinding(bindingId: string): Promise<void> {
  if (USE_MOCK) {
    await mockDelay(undefined);
    return;
  }
  await apiDelete(`/providers/bindings/${encodeURIComponent(bindingId)}`);
}

export function useDeleteBinding(botId?: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteBinding,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["provider-bindings", botId ?? "tenant"] });
    },
  });
}

/** Stable dot colour per provider, so a provider reads the same in the chip
 *  row, the table and the pool strip. Keyed on slug, not on list order. */
export const PROVIDER_DOT: Record<string, string> = {
  azure: "var(--border-accent-blue)",
  cartesia: "var(--border-accent-purple)",
  deepgram: "var(--border-accent-green)",
  elevenlabs: "var(--border-accent-magenta)",
  groq: "var(--border-accent-orange)",
  gladia: "var(--border-accent-teal)",
  speechmatics: "var(--border-accent-lime)",
};

export function providerDot(slug: string): string {
  return PROVIDER_DOT[slug] ?? "var(--border-accent-gray)";
}
