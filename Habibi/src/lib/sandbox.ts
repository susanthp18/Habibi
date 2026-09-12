import type {
  Difficulty,
  Role,
  IntentKey,
  SandboxChunkMeta,
  Persona,
  ScenarioTurn,
  Scenario,
  KbSnapshot,
  SandboxTurn,
  BotReply,
} from "@/api/types/sandbox";

export const INTENT_KEYS = [
  "balance_query",
  "dispute",
  "hardship",
  "waiver_request",
  "payment_intent",
  "upsell_opportunity",
  "escalation",
  "out_of_scope",
] as const;

declare global {
  interface Window {
    __sandboxChunkMeta?: Record<string, SandboxChunkMeta>;
  }
}

/** Cache live RAG chunk titles for seed fallback lookups. */
export function mergeSandboxChunkMeta(
  hits: Array<{
    chunkId: string;
    docTitle?: string | null;
    heading?: string | null;
    snippet?: string | null;
  }>,
): void {
  if (typeof window === "undefined" || hits.length === 0) return;
  const map = (window.__sandboxChunkMeta ??= {});
  for (const c of hits) {
    if (!c.chunkId) continue;
    map[c.chunkId] = {
      docTitle: c.docTitle ?? null,
      heading: c.heading ?? null,
      snippet: c.snippet ?? null,
    };
  }
}

export const INTENT_LABEL: Record<IntentKey, string> = {
  balance_query: "Balance / dues query",
  dispute: "Dispute",
  hardship: "Hardship",
  waiver_request: "Waiver request",
  payment_intent: "Payment intent",
  upsell_opportunity: "Upsell opportunity",
  escalation: "Escalation",
  out_of_scope: "Out of scope",
};

export function chunkTitle(id: string): { doc: string; heading: string; snippet: string } | null {
  const live = (typeof window !== "undefined" ? window.__sandboxChunkMeta : undefined)?.[id];
  if (live) {
    return {
      doc: live.docTitle || id,
      heading: live.heading || "",
      snippet: (live.snippet || "").slice(0, 160),
    };
  }
  return null;
}
