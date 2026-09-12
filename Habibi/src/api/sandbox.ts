// -----------------------------------------------------------------------------
// Call Sandbox — data access seam (PS-3)
//   useScenarios()        → GET /sandbox/scenarios
//   useSandboxRun(id)     → GET /sandbox/runs/{id}
//   createSandboxRun      → POST /sandbox/runs
//   appendSandboxTurn     → POST /sandbox/runs/{id}/turns  (retrieve + Azure chat)
//   exportInteraction     → GET /interactions/{id}/export
//
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type { Guardrails, PersonaState, PromptVersion } from "@/api/types/prompt-studio";
import type { IntentKey, Persona, Scenario } from "@/api/types/sandbox";
import { sandboxTurnResultSchema } from "@/lib/studio-contract";
import { apiGet, apiGetBlob, apiPost } from "./config";
import { INTENT_KEYS } from "@/lib/sandbox";

export type SandboxContext = {
  /** A real `customers` id makes the simulated tools read that borrower's real
   *  rows — the honest rehearsal, and an explicit per-scenario opt-in rather
   *  than a default. Unset leaves the run prompt-only, as before. */
  customer_id?: string;
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
  /** Customer turns before the rehearsal stops for cost; not the card's maxTurns. */
  turnBudget?: number | null;
};

export type SandboxTurnResult = {
  runId: string;
  promptVersionId: string;
  compiledBundleHash?: string | null;
  flowStatus?: "walked" | "validated_not_executed_in_text_rehearsal" | "not_authored" | null;
  /** The step the run is on after this turn; post it back to continue there. */
  nodeKey?: string | null;
  /** What the graph offered the model on this turn: the node's granted tools
   *  plus its generated transitions. */
  offeredTools?: string[] | null;
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
    toolCalls?: Array<{
      name: string;
      ok: boolean;
      simulated?: boolean;
      result?: unknown;
    }>;
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
  /** The step the previous turn ended on. Omit to start the graph. */
  nodeKey?: string | null;
  /** Mock-only fallbacks */
  scenario?: Scenario;
  turnIndex?: number;
  personaState?: PersonaState;
  guardrails?: Guardrails;
}): Promise<SandboxTurnResult> {
  return apiPost<SandboxTurnResult>(
    `/sandbox/runs/${input.runId}/turns`,
    {
      text: input.text,
      history: input.history,
      context: input.context ?? null,
      topK: input.topK ?? 3,
      skillSlug: input.skillSlug ?? null,
      nodeKey: input.nodeKey ?? null,
    },
    { schema: sandboxTurnResultSchema },
  );
}

/**
 * Download the server-assembled call record (transcript, latency split, tool
 * calls, retrievals, guardrails). Goes through {@link apiGetBlob} so the
 * request carries the same auth headers, credentials and timeout as every
 * other live call — the sandbox route used to `fetch` this URL raw, which
 * 401'd in any keyed environment (WP-050).
 */
export async function exportInteraction(
  interactionId: string,
  format: "md" | "json",
): Promise<void> {
  const { blob, headers } = await apiGetBlob(
    `/interactions/${encodeURIComponent(interactionId)}/export?format=${format}`,
  );
  const disposition = headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] || `call-${interactionId}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}

export { INTENT_KEYS } from "@/lib/sandbox";

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

export type TwinCorpusRow = {
  id: string;
  source: string;
  sourceRef: string;
  outcome: Record<string, unknown>;
  taskId?: string | null;
};

export async function fetchTwinCorpus(): Promise<TwinCorpusRow[]> {
  return apiGet<TwinCorpusRow[]>("/eval/twin-corpus");
}

export async function growTwinCorpus(): Promise<{ created: number; skipped: number }> {
  return apiPost<{ created: number; skipped: number }>("/eval/twin-corpus/grow", {});
}

export async function runBounceTwin(twinId = "twin-bounce-ladder-v0"): Promise<TwinRunResult> {
  return apiPost<TwinRunResult>(`/twins/${twinId}/run`, {});
}
