/**
 * BigBound RTVI server→client message contract.
 *
 * Mirrors `backend/voice/rtvi_events.py`. Native RTVI covers transcripts,
 * metrics, speaking state and function calls; these carry our *domain* — which
 * CRM row a tool created, which KB chunks grounded an answer, which Flows node
 * the caller is on.
 *
 * Keep the string literals in sync with the Python emitter.
 */

export type CrmEntityEvent = {
  type: "crm.entity";
  entity: string;
  id: string | null;
  deepLink: string | null;
  tool: string | null;
  summary: string | null;
};

export type RagHitsEvent = {
  type: "rag.hits";
  query: string;
  chunkIds: string[];
  snapshotId: string | null;
  topScore: number | null;
  source: "tool" | "enrich" | string;
};

export type FlowNodeEvent = {
  type: "flow.node";
  name: string;
  previous: string | null;
};

export type LifecycleEvent = {
  type: "session.lifecycle";
  phase: string;
  reason: string | null;
};

export type HandoffStatusEvent = {
  type: "handoff.status";
  /** `callback_queue` until a warm-transfer transport ships. */
  mode: string;
  state: string;
  reason: string | null;
  /** Display name of the assignee routing picked (optional). */
  assignee?: string | null;
  /** Team / queue label (optional). */
  team?: string | null;
  conversationId?: string | null;
};

export type ContextCardEvent = {
  type: "context.card";
  card: string;
};

export type TurnAudioEvent = {
  type: "turn.audio";
  speaker: "user" | "bot" | string;
  sampleRate: number;
  encoding: string;
  pcmBase64: string;
  bytes: number;
};

export type ServerMessage =
  | CrmEntityEvent
  | RagHitsEvent
  | FlowNodeEvent
  | LifecycleEvent
  | HandoffStatusEvent
  | ContextCardEvent
  | TurnAudioEvent;

/** One tool invocation as observed over RTVI, plus any CRM row it produced. */
export type LiveToolCall = {
  id: string;
  name: string;
  /** `running` until a result arrives; the Inspector shows a spinner meanwhile. */
  status: "running" | "done" | "error";
  args?: unknown;
  result?: unknown;
  startedAt: number;
  endedAt?: number;
  entity?: string;
  entityId?: string | null;
  deepLink?: string | null;
};

export type LiveRagHit = {
  id: string;
  query: string;
  chunkIds: string[];
  snapshotId: string | null;
  topScore: number | null;
  source: string;
  at: number;
};

export type LiveTurnAudio = {
  id: string;
  speaker: string;
  sampleRate: number;
  pcmBase64: string;
  bytes: number;
  at: number;
};

export type LiveCallInsights = {
  toolCalls: LiveToolCall[];
  ragHits: LiveRagHit[];
  turnAudio: LiveTurnAudio[];
  /** Latest Flows node name (also the tail of `flowNodeHistory`). */
  flowNode: string | null;
  /** Recent node path for the live chrome breadcrumb (last 3). */
  flowNodeHistory: string[];
  lifecycle: LifecycleEvent | null;
  handoff: HandoffStatusEvent | null;
  contextCard: string | null;
  /** Server-side turn-taking state, from native RTVI speaking events. */
  botSpeaking: boolean;
  userSpeaking: boolean;
  /** 0–1 levels from local AnalyserNode (mic / remote), when available. */
  localLevel: number;
  remoteLevel: number;
};

export const EMPTY_INSIGHTS: LiveCallInsights = {
  toolCalls: [],
  ragHits: [],
  turnAudio: [],
  flowNode: null,
  flowNodeHistory: [],
  lifecycle: null,
  handoff: null,
  contextCard: null,
  botSpeaking: false,
  userSpeaking: false,
  localLevel: 0,
  remoteLevel: 0,
};

/** Narrow an unknown server message payload without trusting its shape. */
export function asServerMessage(data: unknown): ServerMessage | null {
  if (!data || typeof data !== "object") return null;
  const type = (data as { type?: unknown }).type;
  if (typeof type !== "string") return null;
  return data as ServerMessage;
}
