// -----------------------------------------------------------------------------
// Call Sandbox — data access seam (PS-3)
//   useScenarios()        → GET /sandbox/scenarios
//   useSandboxRun(id)     → GET /sandbox/runs/{id}
//   createSandboxRun      → POST /sandbox/runs
//   appendSandboxTurn     → POST /sandbox/runs/{id}/turns  (retrieve + Azure chat)
//
// Mock mode keeps local SCENARIOS + generateBotReply so demos work offline.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  DEFAULT_GUARDRAILS,
  type Guardrails,
  type PersonaState,
  type PromptVersion,
} from "@/data/prompt-studio-seed";
import {
  SCENARIOS,
  generateBotReply,
  INTENT_KEYS,
  type BotReply,
  type IntentKey,
  type Persona,
  type Scenario,
} from "@/data/sandbox-seed";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

export type SandboxContext = {
  customer_name?: string;
  account_no?: string;
  overdue_amount?: string;
  due_date?: string;
  last_payment?: string;
  agent_name?: string;
  bank_name?: string;
  language?: string;
  time_of_day?: string;
};

export type SandboxHistoryItem = { role: "bot" | "customer"; text: string };

export type SandboxChunkHit = {
  chunkId: string;
  docId?: string | null;
  docTitle?: string | null;
  heading?: string | null;
  snippet?: string | null;
  score?: number | null;
};

export type SandboxRun = {
  id: string;
  scenarioId: string | null;
  deploymentId: string | null;
  promptVersionId: string;
  kbSnapshotId: string | null;
  status: "running" | "completed" | "failed";
  openingMessage: string | null;
  promptVersion: PromptVersion;
  context: Record<string, string>;
};

export type SandboxTurnResult = {
  runId: string;
  promptVersionId: string;
  customerTurn: {
    id: string;
    role: "customer";
    text: string;
    intent: string;
    intentScores: Record<string, number>;
    sentiment: number;
    sentimentLabel: "positive" | "neutral" | "negative";
  };
  botTurn: {
    id: string;
    role: "bot";
    text: string;
    chunkIds: string[];
    chunks: SandboxChunkHit[];
    latencyMs: number;
    tokens: number;
    guardrailFlags: string[];
    intent: string;
    sentiment: number;
    sentimentLabel: "positive" | "neutral" | "negative";
    retrievalLogId?: string | null;
    retrieveLatencyMs?: number | null;
    chatLatencyMs?: number | null;
    halted?: boolean;
  };
};

export type SandboxRunDetail = {
  id: string;
  scenarioId: string | null;
  deploymentId: string | null;
  promptVersionId: string | null;
  kbSnapshotId: string | null;
  startedByUserId: string | null;
  status: "running" | "completed" | "failed";
  aggregateLatencyMs: number | null;
  aggregateTokens: number | null;
  createdAt: string | null;
  updatedAt: string | null;
  turns: Array<{
    id: string;
    turnIndex: number;
    role: "bot" | "customer" | "system";
    text: string;
    detectedIntent?: string | null;
    intent?: string | null;
    sentiment?: number | null;
    chunkIds?: string[];
    groundedIn?: Array<{ chunkId: string; docTitle: string; heading?: string; snippet?: string }>;
    guardrailFlags?: string[];
    latencyMs?: number | null;
    tokens?: number | null;
    ts?: number;
    systemKind?: "info" | "warn" | "success" | null;
  }>;
};

function contextFromPersona(persona: Persona): SandboxContext {
  return {
    customer_name: persona.name,
    account_no: persona.phoneLast4 ? `••••${persona.phoneLast4}` : "XXXX",
    overdue_amount: persona.overdue ? `₹${persona.overdue.toLocaleString("en-IN")}` : "0",
    language: persona.language,
    agent_name: "Priya",
    bank_name: "HDFC Bank",
  };
}

export async function fetchSandboxScenarios(): Promise<Scenario[]> {
  if (USE_MOCK) return mockDelay(SCENARIOS);
  const rows = await apiGet<Scenario[]>("/sandbox/scenarios");
  return rows.map((s) => ({
    ...s,
    intents: (s.intents ?? []) as IntentKey[],
    turns: (s.turns ?? []).map((t) => ({
      customer: t.customer,
      expectedIntent: (t.expectedIntent ?? "out_of_scope") as IntentKey,
      expectedSentiment: t.expectedSentiment ?? 0,
      botTemplate: "",
    })),
  }));
}

export function useSandboxScenarios() {
  return useQuery({
    queryKey: ["sandbox-scenarios"],
    queryFn: fetchSandboxScenarios,
    staleTime: 60_000,
  });
}

export async function fetchSandboxRun(runId: string): Promise<SandboxRunDetail> {
  if (USE_MOCK) {
    return mockDelay({
      id: runId,
      scenarioId: null,
      deploymentId: null,
      promptVersionId: null,
      kbSnapshotId: null,
      startedByUserId: null,
      status: "completed",
      aggregateLatencyMs: 0,
      aggregateTokens: 0,
      createdAt: null,
      updatedAt: null,
      turns: [],
    });
  }
  return apiGet<SandboxRunDetail>(`/sandbox/runs/${runId}`);
}

export function useSandboxRun(runId: string | null | undefined) {
  return useQuery({
    queryKey: ["sandbox-run", runId],
    queryFn: () => fetchSandboxRun(runId!),
    enabled: Boolean(runId),
    staleTime: 5_000,
  });
}

export async function createSandboxRun(input: {
  promptVersionId?: string | null;
  scenarioId?: string;
  scenarioTitle?: string;
  kbSnapshotId?: string | null;
  openingTemplate?: string;
  persona?: Persona;
  context?: SandboxContext;
}): Promise<SandboxRun> {
  const context = {
    ...contextFromPersona(
      input.persona ?? {
        name: "Customer",
        phoneLast4: "0000",
        product: "—",
        dpd: 0,
        overdue: 0,
        mood: "neutral",
        language: "English",
      },
    ),
    ...input.context,
  };

  if (USE_MOCK) {
    const opening = (input.openingTemplate ?? "")
      .replaceAll("{customer_name}", context.customer_name ?? "Customer")
      .replaceAll("{agent_name}", context.agent_name ?? "Priya")
      .replaceAll("{bank_name}", context.bank_name ?? "HDFC Bank")
      .replaceAll("{language}", context.language ?? "English");
    return mockDelay({
      id: `SBX-MOCK-${Date.now().toString(36)}`,
      scenarioId: input.scenarioId ?? null,
      deploymentId: null,
      promptVersionId: input.promptVersionId ?? "v1_4",
      kbSnapshotId: input.kbSnapshotId ?? null,
      status: "running",
      openingMessage: opening || null,
      promptVersion: {
        id: input.promptVersionId ?? "v1_4",
        label: "mock",
        author: "You",
        status: "published",
        createdAt: new Date().toISOString(),
        summary: "",
        prompt: "",
        persona: {
          traits: { empathy: 70, firmness: 50, formality: 60, verbosity: 40, upsell: 20 },
          language: "English",
          fallbackLanguages: ["Hindi"],
        },
        voice: { voiceId: "priya", speed: 1, pitch: 0, warmth: 60, pauseMs: 300, sampleText: "" },
        guardrails: DEFAULT_GUARDRAILS,
      },
      context: Object.fromEntries(
        Object.entries(context)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ),
    });
  }

  return apiPost<SandboxRun>("/sandbox/runs", {
    promptVersionId: input.promptVersionId ?? null,
    scenarioId: input.scenarioId ?? null,
    scenarioTitle: input.scenarioTitle ?? null,
    kbSnapshotId: input.kbSnapshotId ?? null,
    openingTemplate: input.openingTemplate ?? null,
    persona: input.persona ?? null,
    context,
  });
}

export async function appendSandboxTurn(input: {
  runId: string;
  text: string;
  history: SandboxHistoryItem[];
  context?: SandboxContext;
  topK?: number;
  skillSlug?: string;
  /** Mock-only fallbacks */
  scenario?: Scenario;
  turnIndex?: number;
  personaState?: PersonaState;
  guardrails?: Guardrails;
}): Promise<SandboxTurnResult> {
  if (USE_MOCK) {
    if (!input.scenario) throw new Error("sandbox_scenario_required");
    if (!input.personaState) throw new Error("sandbox_persona_state_required");
    const scenario = input.scenario;
    const reply: BotReply = generateBotReply(
      scenario,
      input.turnIndex ?? 0,
      input.text,
      input.personaState,
      input.guardrails ?? DEFAULT_GUARDRAILS,
    );
    await mockDelay(null, reply.latencyMs);
    return {
      runId: input.runId,
      promptVersionId: "mock",
      customerTurn: {
        id: `c-${Date.now()}`,
        role: "customer",
        text: input.text,
        intent: reply.intent,
        intentScores: reply.intentScores,
        sentiment: 0,
        sentimentLabel: "neutral",
      },
      botTurn: {
        id: `b-${Date.now()}`,
        role: "bot",
        text: reply.text,
        chunkIds: reply.chunkIds,
        chunks: reply.chunkIds.map((id) => ({ chunkId: id })),
        latencyMs: reply.latencyMs,
        tokens: reply.tokens,
        guardrailFlags: reply.guardrailFlags,
        intent: reply.intent,
        sentiment: 0,
        sentimentLabel: "neutral",
        halted: false,
      },
    };
  }

  return apiPost<SandboxTurnResult>(`/sandbox/runs/${input.runId}/turns`, {
    text: input.text,
    history: input.history,
    context: input.context ?? null,
    topK: input.topK ?? 3,
    skillSlug: input.skillSlug ?? null,
  });
}

export { INTENT_KEYS };

export function isIntentKey(value: string): value is IntentKey {
  return (INTENT_KEYS as readonly string[]).includes(value);
}

/** The one list of grounding sources a bot turn is rendered from.
 *
 * The turn card used to build its "N chunks" counter from `chunkIds` and its
 * "grounded in …" chips from `chunks`, which are two different fields. A turn
 * that matched only FAQ rows therefore showed three chips above a footer that
 * read "0 chunks" (rehearsal 2026-08-25). Counter, chips and the expanded id
 * list all read this, so they cannot disagree.
 *
 * `chunkIds` is a fallback, not a second opinion: paths that send ids only
 * (the mock reply) still get chips, labelled by id via {@link groundedLabel}.
 */
export function groundedSources(turn: {
  chunks?: SandboxChunkHit[] | null;
  chunkIds?: string[] | null;
}): SandboxChunkHit[] {
  if (turn.chunks?.length) return turn.chunks;
  return (turn.chunkIds ?? []).map((chunkId) => ({ chunkId }));
}

/** Doc-title chip label for grounded retrieval. */
export function groundedLabel(chunk: SandboxChunkHit): string {
  const title = (chunk.docTitle || "").trim();
  if (title) return title;
  return chunk.chunkId;
}

export type TwinRunResult = {
  id: string;
  twinId: string;
  scenario: string;
  status: string;
  outcome: {
    queues?: { whatsapp?: unknown[]; sms?: unknown[]; voice?: unknown[] };
    ledger?: Record<string, unknown>;
    dialled?: boolean;
  };
  grader: { passed?: boolean };
};

export async function runBounceTwin(twinId = "twin-bounce-ladder-v0"): Promise<TwinRunResult> {
  if (USE_MOCK) {
    return mockDelay({
      id: "mock-twin",
      twinId,
      scenario: "bounce_ladder",
      status: "completed",
      outcome: {
        queues: { whatsapp: [{ kind: "bounce_chase" }], sms: [], voice: [] },
        ledger: { lastEvent: "bounce_chase_whatsapp" },
        dialled: false,
      },
      grader: { passed: true },
    });
  }
  return apiPost<TwinRunResult>(`/twins/${twinId}/run`, {});
}
