/**
 * Domain / wire types for the sandbox surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

import type { Guardrails, PersonaState } from "./prompt-studio";

export type Difficulty = "easy" | "medium" | "hard";
export type Role = "bot" | "customer" | "system";
export type IntentKey =
  | "balance_query"
  | "dispute"
  | "hardship"
  | "waiver_request"
  | "payment_intent"
  | "upsell_opportunity"
  | "escalation"
  | "out_of_scope";
export type SandboxChunkMeta = {
  docTitle?: string | null;
  heading?: string | null;
  snippet?: string | null;
};
export type Persona = {
  name: string;
  phoneLast4: string;
  product: string;
  dpd: number;
  overdue: number;
  mood: string;
  language: string;
};
export type ScenarioTurn = {
  customer: string;
  expectedIntent: IntentKey;
  expectedSentiment: number; // -1..1
  botTemplate: string; // {trait} placeholders resolved at runtime
  chunkIds?: string[];
};
export type Scenario = {
  id: string;
  title: string;
  summary: string;
  difficulty: Difficulty;
  intents: IntentKey[];
  persona: Persona;
  openingBot: string;
  turns: ScenarioTurn[];
};
export type KbSnapshot = { id: string; label: string; note: string };
export type SandboxTurn = {
  id: string;
  role: Role;
  text: string;
  ts: number;
  intent?: IntentKey;
  intentScores?: Record<IntentKey, number>;
  sentiment?: number;
  chunkIds?: string[];
  /** Live RAG hits with doc titles — preferred over seed chunkTitle lookup. */
  chunks?: Array<{
    chunkId: string;
    docId?: string | null;
    docTitle?: string | null;
    heading?: string | null;
    snippet?: string | null;
    score?: number | null;
  }>;
  latencyMs?: number;
  tokens?: number;
  guardrailFlags?: string[];
  systemKind?: "info" | "warn" | "success";
};
// ---------- bot reply generator ----------
export type BotReply = {
  text: string;
  chunkIds: string[];
  latencyMs: number;
  tokens: number;
  guardrailFlags: string[];
  intent: IntentKey;
  intentScores: Record<IntentKey, number>;
};
