// -----------------------------------------------------------------------------
// Persona & Prompt Studio — data access seam
//   Reads  (PS-1): versions / presets / voices / deployments
//   Writes (PS-2): draft create/patch, publish, restore-as-draft, rollback
// -----------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  Guardrails,
  PersonaPreset,
  PersonaState,
  PromptVersion,
  VoiceConfig,
} from "@/api/types/prompt-studio";
import { ApiError, apiGet, apiPatch, apiPost, isNotFound, retryUnlessClientError } from "./config";
import type { AgentCard } from "./agent-card";
import type { FlowGraph } from "./flow";
import { stableStringify } from "@/lib/stable-stringify";

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
  /** The split this deployment is actually taking. */
  trafficPct?: number;
  evalReportId?: string | null;
  frozenTools?: string[] | null;
  bundleHash?: string | null;
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
  /**
   * Deliberately replace a stored graph that does not parse. The PATCH refuses
   * the empty sentinel over an unreadable column without it, which is what
   * stopped an autosave from erasing one.
   */
  replaceUnreadable?: boolean;
  botId?: string;
  agentCard?: AgentCard;
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
  /** See `PromptVersionDraftInput.replaceUnreadable`. */
  replaceUnreadable?: boolean;
  /** Omitted leaves the stored card untouched — same key-present rule as flow. */
  agentCard?: AgentCard;
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
  if (body.replaceUnreadable) patch.replaceUnreadable = true;
  if (body.agentCard) patch.agentCard = body.agentCard;
  return patch;
}

const VERSIONS_KEY = ["prompt-versions"] as const;

const PUBLISHED_KEY = ["prompt-versions", "published"] as const;

const DEPLOYMENTS_KEY = ["bot-deployments"] as const;

function invalidatePromptStudio(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: VERSIONS_KEY });
  void qc.invalidateQueries({ queryKey: PUBLISHED_KEY });
  void qc.invalidateQueries({ queryKey: DEPLOYMENTS_KEY });
  // Experiments live under ["deployments"], not ["bot-deployments"]. A rollback
  // that only invalidates one of those two left Ship reading a stale canary.
  void qc.invalidateQueries({ queryKey: ["deployments"] });
  // A publish is the single biggest thing that happens to a card, and it lands
  // in two places this key set does not otherwise reach: the fleet list (which
  // shows deploymentStatus / lastPublish / draft chips) and the change log,
  // whose whole job is to have already recorded it. Neither is a prefix of
  // ["prompt-versions"], so both were stale on the screen that caused them.
  void qc.invalidateQueries({ queryKey: ["agent-studio"] });
  void qc.invalidateQueries({ queryKey: ["agent-change-log"] });
  // The Outbound tab offers the *published* card's missions, so a publish is
  // exactly when that list changes -- and it never refreshed.
  void qc.invalidateQueries({ queryKey: ["outbound", "missions"] });
}

// ---------- reads ----------

/** One page of history. When a card has more, the drawer says the list is cut. */
export const VERSION_HISTORY_PAGE = 200;

export async function fetchPromptVersions(botId?: string): Promise<PromptVersion[]> {
  const q = new URLSearchParams({ limit: String(VERSION_HISTORY_PAGE) });
  if (botId) q.set("botId", botId);
  return apiGet<PromptVersion[]>(`/prompt-versions?${q.toString()}`);
}

export async function fetchPublishedPromptVersion(botId?: string): Promise<PromptVersion | null> {
  const q = botId ? `?botId=${encodeURIComponent(botId)}` : "";
  try {
    return await apiGet<PromptVersion>(`/prompt-versions/published${q}`);
  } catch (err) {
    // Only a 404 means "this card has never published". Anything else — a 500,
    // a timeout, the API being down — is a failure, and flattening it to null
    // made the studio announce "never published" for a card that is serving
    // production traffic, and hide its rollback panel while it did. The caller
    // renders an outage as an outage; it can only do that if one reaches it.
    if (isNotFound(err)) return null;
    throw err;
  }
}

export async function fetchPersonaPresets(): Promise<PersonaPreset[]> {
  return apiGet<PersonaPreset[]>("/persona-presets");
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
  /** Which vendor synced this voice. Defaults to azure — every row that
   *  predates the provider registry came from the Azure catalog sync. */
  providerId?: string;
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
  /** Filter to one vendor. Server-side: the list is keyset-paginated, so a
   *  client-side filter would only ever filter the page already fetched. */
  providerId?: string;
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
  const q = new URLSearchParams();
  if (params.q) q.set("q", params.q);
  if (params.locale) q.set("locale", params.locale);
  if (params.gender) q.set("gender", params.gender);
  if (params.status) q.set("status", params.status);
  if (params.priceTier) q.set("price_tier", params.priceTier);
  if (params.providerId) q.set("providerId", params.providerId);
  if (params.includePremium) q.set("include_premium", "true");
  if (params.includeRemoved) q.set("include_removed", "true");
  if (params.limit) q.set("limit", String(params.limit));
  if (params.cursor) q.set("cursor", params.cursor);
  const qs = q.toString();
  return apiGet<TtsCatalogList>(`/tts-voices/catalog${qs ? `?${qs}` : ""}`);
}

export async function fetchTtsVoiceDetail(shortName: string): Promise<TtsCatalogVoice> {
  return apiGet<TtsCatalogVoice>(`/tts-voices/catalog/${encodeURIComponent(shortName)}`);
}

export async function fetchTtsPricing(): Promise<TtsPriceTier[]> {
  return apiGet<TtsPriceTier[]>("/tts-voices/pricing");
}

export async function syncTtsVoiceCatalog(): Promise<TtsSyncRun> {
  return apiPost<TtsSyncRun>("/tts-voices/catalog/sync", {});
}

export async function fetchTtsSyncRuns(limit = 20): Promise<TtsSyncRun[]> {
  return apiGet<TtsSyncRun[]>(`/tts-voices/catalog/sync-runs?limit=${limit}`);
}

export async function fetchTtsVoiceWarning(shortName: string): Promise<TtsVoiceWarning | null> {
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

export type PromptTokenEstimate = {
  /** The authored text alone — what the editor holds. */
  tokens: number;
  encoding: string;
  usdPer1M: number;
  /** Input cost of the authored text alone. */
  costUsd: number;
  source: "tiktoken" | "heuristic";
  /**
   * The whole system message as the runtime assembles it: authored prompt plus
   * generated guardrail rules, persona directions, tenant-local time and, on
   * voice, the naturalness overlay. `null` when no guardrails were sent, since
   * the assembly would then be a guess presented as a measurement.
   *
   * This is the figure that bills — it is re-sent on every LLM call, two or
   * three times a turn through Flows.
   */
  assembledTokens: number | null;
  assembledCostUsd: number | null;
};

export type PromptTokenEstimateInput = {
  prompt: string;
  /** Supplying these is what makes the answer describe the call. */
  guardrails?: Guardrails;
  persona?: PersonaState;
  channel?: "voice" | "text";
  /** The card whose skill catalog rides on the system message. */
  botId?: string;
};

export async function estimatePromptTokens(
  input: PromptTokenEstimateInput,
): Promise<PromptTokenEstimate> {
  return apiPost<PromptTokenEstimate>("/prompt-versions/estimate-tokens", {
    prompt: input.prompt,
    ...(input.guardrails ? { guardrails: input.guardrails } : {}),
    ...(input.persona ? { persona: input.persona } : {}),
    ...(input.channel ? { channel: input.channel } : {}),
    ...(input.botId ? { botId: input.botId } : {}),
  });
}

/** Debounced tiktoken estimate for the Prompt Studio editor footer. */
export function usePromptTokenEstimate(input: PromptTokenEstimateInput) {
  const [debounced, setDebounced] = useState(input);
  // Serialised, not compared by reference: `guardrails` and `persona` are fresh
  // object literals on every render of the Studio, so a dependency on the
  // objects themselves would restart the debounce timer forever and the figure
  // would never settle.
  const key = stableStringify(input);
  useEffect(() => {
    const t = window.setTimeout(
      () => setDebounced(JSON.parse(key) as PromptTokenEstimateInput),
      250,
    );
    return () => window.clearTimeout(t);
  }, [key]);

  return useQuery({
    queryKey: ["prompt-studio", "token-estimate", stableStringify(debounced)],
    queryFn: () => estimatePromptTokens(debounced),
    placeholderData: (prev) => prev,
    // Not before the editor has anything in it. The Studio mounts with an empty
    // prompt and hydrates a tick later, so an unguarded query spends a request
    // measuring the empty string and briefly renders its answer as the card's.
    enabled: debounced.prompt.trim().length > 0,
    // A 400/422 here is a verdict about this exact body and will be identical
    // three milliseconds later; RQ's default of three tries just sends it again.
    retry: retryUnlessClientError,
    staleTime: 30_000,
  });
}

// ---------- writes ----------

export async function createPromptVersion(input: PromptVersionDraftInput): Promise<PromptVersion> {
  return apiPost<PromptVersion>("/prompt-versions", input);
}

export async function patchPromptVersion(
  versionId: string,
  input: PromptVersionPatchInput,
): Promise<PromptVersion> {
  return apiPatch<PromptVersion>(`/prompt-versions/${versionId}`, input);
}

export async function publishPromptVersion(
  versionId: string,
  summary = "",
  opts?: {
    kbSnapshotId?: string | null;
    trafficPct?: number | null;
    autoRollback?: string[] | null;
  },
): Promise<PromptVersion> {
  return apiPost<PromptVersion>(`/prompt-versions/${versionId}/publish`, {
    summary,
    kbSnapshotId: opts?.kbSnapshotId ?? null,
    trafficPct: opts?.trafficPct ?? null,
    autoRollback: opts?.autoRollback ?? null,
  });
}

export async function restorePromptVersionAsDraft(versionId: string): Promise<PromptVersion> {
  return apiPost<PromptVersion>(`/prompt-versions/${versionId}/restore-as-draft`, {});
}

export async function rollbackBotDeployment(deploymentId: string): Promise<BotDeployment> {
  return apiPost<BotDeployment>(`/bot-deployments/${deploymentId}/rollback`, {});
}

export async function discardPromptVersion(versionId: string): Promise<PromptVersion> {
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
    meta: { errors: "caller" },
    mutationFn: discardPromptVersion,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useRollbackBotDeployment() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: rollbackBotDeployment,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useLintPrompt() {
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: lintPromptVersion,
  });
}

/**
 * The deterministic lint, run continuously rather than on a button.
 *
 * It used to be a header button, and the cost of that was measurable: linting
 * the thirteen prompt versions in the database found sixteen CRM tokens across
 * four cards, three of them published — including the card every inbound call
 * resolves to, whose live system prompt loses two of its six authored lines
 * before the model sees them. Nobody had pressed the button.
 *
 * There is no reason it needed one. The pass is deterministic, has no LLM in
 * it, and answers a question the author is asking continuously while typing —
 * "will the runtime keep what I just wrote?". Debounced and cached exactly like
 * `usePromptTokenEstimate` above, which already runs per edit in the same
 * editor against the same server.
 *
 * `includeLlm` is deliberately not a parameter. The costed Azure pass stays an
 * explicit action; this is the free half.
 */
export function useAutoLint(input: { prompt: string; guardrails: Guardrails }) {
  const [debounced, setDebounced] = useState(input);
  // Serialised for the same reason the estimate is: `guardrails` is a fresh
  // object literal on every Studio render, so depending on the object would
  // restart the timer forever and findings would never appear.
  const key = stableStringify(input);
  useEffect(() => {
    const t = window.setTimeout(
      () => setDebounced(JSON.parse(key) as { prompt: string; guardrails: Guardrails }),
      400,
    );
    return () => window.clearTimeout(t);
  }, [key]);

  return useQuery({
    queryKey: ["prompt-studio", "auto-lint", stableStringify(debounced)],
    queryFn: () => lintPromptVersion({ ...debounced, includeLlm: false }),
    // Same two guards as the token estimate: nothing to lint before hydration,
    // and a rejected body stays rejected however many times it is resent.
    enabled: debounced.prompt.trim().length > 0,
    retry: retryUnlessClientError,
    // No placeholderData: a stale finding list is worse than none. Findings
    // point at spans in text that has since changed, and "your prompt is clean"
    // is the one thing this must never say by accident.
    staleTime: 30_000,
  });
}

export async function fetchActiveBotDeployment(
  environment: "production" | "sandbox" = "production",
  botId?: string,
): Promise<BotDeployment | null> {
  const q = new URLSearchParams({ environment });
  if (botId) q.set("botId", botId);
  try {
    return await apiGet<BotDeployment>(`/bot-deployments/active?${q.toString()}`);
  } catch (err) {
    // 404 is `active_deployment_not_found` — a real, reportable absence. The
    // backend is careful to distinguish that from a fault; see the note on the
    // published-version fetcher above for what discarding the difference cost.
    if (isNotFound(err)) return null;
    throw err;
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
  // The status is the real signal: 404 (the draft was discarded under us) and
  // 409 (it has since been published, so it is no longer a draft) both mean
  // "create a new draft instead". The message sniff below is kept only for the
  // mock transport, which throws plain Errors with no status.
  if (err instanceof ApiError) return err.status === 404 || err.status === 409;
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

/** What the editor holds that a draft is made from; `draftId` names the one to patch. */
type EditorDraftOpts = Pick<
  PromptVersionDraftInput,
  "label" | "prompt" | "persona" | "voice" | "guardrails" | "flow" | "agentCard" | "botId"
> & { draftId?: string | null; label: string };

/** Create-or-patch a draft from editor state, then publish it. */
export async function publishStudioDraft(
  opts: EditorDraftOpts & { summary: string; trafficPct?: number; autoRollback?: string[] },
): Promise<PromptVersion> {
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
    autoRollback: opts.autoRollback,
  });
}

/** Ensure a draft exists for Sandbox try-out / autosave of editor state. */
export async function ensureStudioDraft(
  opts: EditorDraftOpts & { replaceUnreadable?: boolean; summary?: string },
): Promise<PromptVersion> {
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
  if (opts.replaceUnreadable) body.replaceUnreadable = true;
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
    meta: { errors: "caller" },
    mutationFn: publishStudioDraft,
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useRestorePromptVersionAsDraft() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (versionId: string) => restorePromptVersionAsDraft(versionId),
    onSuccess: () => invalidatePromptStudio(qc),
  });
}

export function useEnsureStudioDraft() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: ensureStudioDraft,
    // Narrow: a keystroke's autosave used to refetch the fleet, the card and
    // any mounted compile preview -- a sixteen-gate POST per save.
    onSuccess: (_row, vars) => {
      void qc.invalidateQueries({ queryKey: VERSIONS_KEY });
      void qc.invalidateQueries({ queryKey: ["agent-studio", "card", vars.botId] });
    },
  });
}

/**
 * Refresh the voice catalogue from every provider. Every read the sync can
 * move is invalidated, not only the three obvious ones: the counts feeding
 * the provider chips and the locale dropdown are derived from the same table
 * with a 60s staleTime, so "Catalog refreshed" used to appear over a locale
 * list and provider tallies still describing the pre-sync catalogue.
 */
export function useSyncTtsVoiceCatalog() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: syncTtsVoiceCatalog,
    onSuccess: () => {
      for (const key of [
        "tts-voice-catalog-infinite",
        "tts-voice-catalog",
        "tts-voice-sync-runs",
        "tts-voice-provider-counts",
        "tts-voice-locale-counts",
        "tts-voices",
      ]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
