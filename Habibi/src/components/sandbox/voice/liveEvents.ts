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

/**
 * Who the call is really about, once verification succeeds.
 *
 * Distinct from the rehearsal persona: the persona is the name the tester typed
 * into the Sandbox, while this is the CRM record every tool from here on
 * returns. When they differ — and in a sandbox they usually do — the header
 * must show this one.
 */
export type IdentityVerifiedEvent = {
  type: "identity.verified";
  customerName: string | null;
  customerId: string | null;
  method: string | null;
};

/**
 * Server-side analysis for one turn, keyed by `turnIndex`.
 *
 * The browser only ever saw turn *text* over RTVI, so the Inspector's Intent,
 * Sentiment and Metrics tabs rendered their empty states for entire live calls
 * — while the backend was classifying every turn and measuring every stage and
 * writing both to Postgres. This carries that work to the client instead of
 * re-deriving a weaker version of it in the browser.
 *
 * Customer turns arrive twice: `source: "keyword"` immediately, then
 * `source: "llm"` when the refinement lands. Later fields overwrite earlier
 * ones for the same `turnIndex`; absent fields leave the previous value alone.
 */
export type TurnAnalysisEvent = {
  type: "turn.analysis";
  turnIndex: number;
  speaker?: "customer" | "bot";
  text?: string;
  atSec?: number;
  sentiment?: number;
  sentimentLabel?: string;
  intent?: string;
  intentScores?: Record<string, number>;
  interrupted?: boolean;
  ttfbMs?: number;
  ttfaMs?: number;
  tokens?: number;
  sttTtfbMs?: number;
  llmTtfbMs?: number;
  ttsTtfbMs?: number;
  userTurnMs?: number;
  aggregationMs?: number;
  toolMs?: number;
  source?: "keyword" | "llm";
};

/** The CRM interaction backing this call, sent once on connect. */
export type SessionBoundEvent = {
  type: "session.bound";
  interactionId: string | null;
  customerId: string | null;
};

export type ServerMessage =
  | SessionBoundEvent
  | CrmEntityEvent
  | RagHitsEvent
  | FlowNodeEvent
  | LifecycleEvent
  | HandoffStatusEvent
  | ContextCardEvent
  | IdentityVerifiedEvent
  | TurnAnalysisEvent
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
  /** CRM interaction backing this call — unlocks the server-backed Trace tab. */
  interactionId: string | null;
  /** Set once verify_identity succeeds; overrides the persona in the header. */
  verifiedCustomer: IdentityVerifiedEvent | null;
  /**
   * Server-side per-turn analysis, ascending by `turnIndex`.
   *
   * Kept beside the turn list rather than merged into it: `SandboxTurn` is the
   * text-rehearsal model, and a live call has an authoritative server index
   * that the browser's append order cannot be trusted to reproduce. The tabs
   * read this when it is populated and fall back to `turns` for rehearsal.
   */
  turnAnalysis: TurnAnalysisEvent[];
  /** Server-side turn-taking state, from native RTVI speaking events. */
  botSpeaking: boolean;
  userSpeaking: boolean;
  /** 0–1 levels from local AnalyserNode (mic / remote), when available. */
  localLevel: number;
  remoteLevel: number;
};

/**
 * Apply one analysis payload to the ordered list.
 *
 * Merges by `turnIndex` and keeps ascending order, because a customer turn is
 * reported twice — the keyword baseline first, then the LLM refinement — and
 * the refinement omits every field it does not revise. Spreading the update
 * over the existing entry is what makes the second message a correction rather
 * than a replacement that would blank the text and timings.
 */
export function mergeTurnAnalysis(
  prev: TurnAnalysisEvent[],
  next: TurnAnalysisEvent,
): TurnAnalysisEvent[] {
  const at = prev.findIndex((t) => t.turnIndex === next.turnIndex);
  if (at >= 0) {
    const merged = [...prev];
    merged[at] = { ...merged[at], ...next };
    return merged;
  }
  const out = [...prev, next];
  out.sort((a, b) => a.turnIndex - b.turnIndex);
  return out;
}

export const EMPTY_INSIGHTS: LiveCallInsights = {
  toolCalls: [],
  ragHits: [],
  turnAudio: [],
  flowNode: null,
  flowNodeHistory: [],
  lifecycle: null,
  handoff: null,
  contextCard: null,
  interactionId: null,
  verifiedCustomer: null,
  turnAnalysis: [],
  botSpeaking: false,
  userSpeaking: false,
  localLevel: 0,
  remoteLevel: 0,
};

/** Narrow an unknown server message payload without trusting its shape. */
export function asServerMessage(data: unknown): ServerMessage | null {
  if (!data || typeof data !== "object") return null;
  const o = data as Record<string, unknown>;
  const type = o.type;
  if (typeof type !== "string") return null;

  switch (type) {
    case "crm.entity": {
      if (typeof o.entity !== "string") return null;
      return {
        type,
        entity: o.entity,
        id: typeof o.id === "string" || o.id === null ? o.id : null,
        deepLink: typeof o.deepLink === "string" || o.deepLink === null ? o.deepLink : null,
        tool: typeof o.tool === "string" || o.tool === null ? o.tool : null,
        summary: typeof o.summary === "string" || o.summary === null ? o.summary : null,
      };
    }
    case "rag.hits": {
      if (typeof o.query !== "string") return null;
      if (!Array.isArray(o.chunkIds) || !o.chunkIds.every((id) => typeof id === "string"))
        return null;
      return {
        type,
        query: o.query,
        chunkIds: o.chunkIds,
        snapshotId: typeof o.snapshotId === "string" || o.snapshotId === null ? o.snapshotId : null,
        topScore: typeof o.topScore === "number" || o.topScore === null ? o.topScore : null,
        source: typeof o.source === "string" ? o.source : "tool",
      };
    }
    case "flow.node": {
      if (typeof o.name !== "string" || !o.name.trim()) return null;
      return {
        type,
        name: o.name,
        previous: typeof o.previous === "string" || o.previous === null ? o.previous : null,
      };
    }
    case "session.bound": {
      return {
        type,
        interactionId: typeof o.interactionId === "string" ? o.interactionId : null,
        customerId: typeof o.customerId === "string" ? o.customerId : null,
      };
    }
    case "turn.analysis": {
      // turnIndex is the merge key — a payload without one cannot be applied.
      if (typeof o.turnIndex !== "number" || !Number.isFinite(o.turnIndex)) return null;
      const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
      const str = (v: unknown) => (typeof v === "string" && v ? v : undefined);
      const scores =
        o.intentScores && typeof o.intentScores === "object" && !Array.isArray(o.intentScores)
          ? (Object.fromEntries(
              Object.entries(o.intentScores as Record<string, unknown>).filter(
                ([, v]) => typeof v === "number" && Number.isFinite(v),
              ),
            ) as Record<string, number>)
          : undefined;
      return {
        type,
        turnIndex: o.turnIndex,
        speaker: o.speaker === "bot" || o.speaker === "customer" ? o.speaker : undefined,
        text: str(o.text),
        atSec: num(o.atSec),
        sentiment: num(o.sentiment),
        sentimentLabel: str(o.sentimentLabel),
        intent: str(o.intent),
        intentScores: scores && Object.keys(scores).length ? scores : undefined,
        interrupted: typeof o.interrupted === "boolean" ? o.interrupted : undefined,
        ttfbMs: num(o.ttfbMs),
        ttfaMs: num(o.ttfaMs),
        tokens: num(o.tokens),
        sttTtfbMs: num(o.sttTtfbMs),
        llmTtfbMs: num(o.llmTtfbMs),
        ttsTtfbMs: num(o.ttsTtfbMs),
        userTurnMs: num(o.userTurnMs),
        aggregationMs: num(o.aggregationMs),
        toolMs: num(o.toolMs),
        source: o.source === "llm" || o.source === "keyword" ? o.source : undefined,
      };
    }
    case "identity.verified": {
      return {
        type,
        customerName: typeof o.customerName === "string" ? o.customerName : null,
        customerId: typeof o.customerId === "string" ? o.customerId : null,
        method: typeof o.method === "string" ? o.method : null,
      };
    }
    case "session.lifecycle": {
      if (typeof o.phase !== "string") return null;
      return {
        type,
        phase: o.phase,
        reason: typeof o.reason === "string" || o.reason === null ? o.reason : null,
      };
    }
    case "handoff.status": {
      if (typeof o.mode !== "string" || typeof o.state !== "string") return null;
      return {
        type,
        mode: o.mode,
        state: o.state,
        reason: typeof o.reason === "string" || o.reason === null ? o.reason : null,
        assignee: typeof o.assignee === "string" || o.assignee === null ? o.assignee : undefined,
        team: typeof o.team === "string" || o.team === null ? o.team : undefined,
        conversationId:
          typeof o.conversationId === "string" || o.conversationId === null
            ? o.conversationId
            : undefined,
      };
    }
    case "context.card": {
      if (typeof o.card !== "string") return null;
      return { type, card: o.card };
    }
    case "turn.audio": {
      if (typeof o.pcmBase64 !== "string" || !o.pcmBase64.trim()) return null;
      if (typeof o.speaker !== "string") return null;
      // Positive, not merely finite: this feeds `new AudioContext({sampleRate})`.
      if (typeof o.sampleRate !== "number" || !Number.isFinite(o.sampleRate) || o.sampleRate <= 0)
        return null;
      if (typeof o.encoding !== "string") return null;
      if (typeof o.bytes !== "number" || !Number.isFinite(o.bytes)) return null;
      return {
        type,
        speaker: o.speaker,
        sampleRate: o.sampleRate,
        encoding: o.encoding,
        pcmBase64: o.pcmBase64,
        bytes: o.bytes,
      };
    }
    default:
      return null;
  }
}
