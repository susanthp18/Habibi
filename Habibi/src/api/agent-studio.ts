import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { stableStringify } from "@/lib/stable-stringify";
import { compileReportSchema, effectiveContractSchema } from "@/lib/studio-contract";
import { apiGet, apiPatch, apiPost, retryUnlessClientError } from "./config";
import type { AgentCard } from "./agent-card";

export type AgentCardSummary = {
  botId: string;
  name: string;
  version: string;
  slug: string;
  purpose: string;
  channels: string[];
  skills: string[];
  toolCount: number;
  evalStatus: string;
  /** null when no active production deployment — the card takes no traffic. */
  trafficPct: number | null;
  deploymentStatus: "live" | "published" | "draft" | "empty";
  lastPublish: string | null;
  promptVersionId: string | null;
  draftVersionId: string | null;
  hasDraft: boolean;
  /** Where `agentCard` came from: the draft the editor edits, or the live row. */
  cardSource: "draft" | "published" | "default" | "scaffold";
  /** The bot inbound traffic resolves to (BOT_ID). One per environment. */
  entryBotId: string;
  /**
   * The enabled entry bindings that land on this card, from the table the
   * door routes by. `address: null` is the channel default. Empty when the
   * door is off or nothing is bound here.
   */
  entryBindings: EntryBinding[];
  /**
   * Routing, not deployment. `entry` is the bot BOT_ID resolves to; `handoff`
   * is reached through some live card's allowlist; `direct` holds its own
   * active deployment so it is addressable by bot_id even though nothing hands
   * off to it (Intake is the shipped example); `unreachable` has neither a
   * deployment nor an inbound edge, and is the only one that means dead config.
   */
  reachability: "entry" | "handoff" | "direct" | "unreachable" | "archived";
  archivedAt: string | null;
  /** Re-seeded on API boot, so it can never be archived. */
  isFirstParty: boolean;
  /** The editable card (draft when one exists). */
  agentCard: AgentCard;
  /** What production is actually running. `{}` until first publish (every field is optional). */
  publishedCard: AgentCard;
};

export type EntryBinding = {
  id: string;
  channel: string;
  address: string | null;
  bot_id: string;
  enabled: boolean;
  note: string;
  updated_at: string | null;
};

/** PUT /agent-studio/entry-bindings. CamelCase `botId`; GET rows use `bot_id`. */
export type EntryBindingUpsert = {
  channel: string;
  botId: string;
  address?: string | null;
  note?: string;
  enabled?: boolean;
};

/** Strip GET-only keys so a round-trip body does not 422 extra_forbidden. */
export function entryBindingUpsertBody(b: EntryBinding): EntryBindingUpsert {
  return {
    channel: b.channel,
    botId: b.bot_id,
    address: b.address,
    note: b.note,
    enabled: b.enabled,
  };
}

/** "answers +1937… · whatsapp default" — one chip per binding. */
export function entryBindingLabel(b: EntryBinding): string {
  return b.address ? `answers ${b.address} · ${b.channel}` : `${b.channel} default`;
}

export type CompileGate = {
  gate: string;
  name: string;
  status: "pass" | "fail" | "warn" | "skipped";
  detail: string;
  issues: unknown[];
};

export type CompileReport = {
  // The API serialises the model as-is, so this is snake_case, not botId.
  bot_id: string;
  gates: CompileGate[];
  effective_tools: string[];
  idle_tools: string[];
  /** What G6 gates on — not `idle_tools.length`, which includes platform tools. */
  idle_voice_tools: number;
  voice_tool_cap: number;
  skill_description_tokens: number;
  /** The card as compiled: defaults applied, the grant resolved. */
  card: AgentCard;
  bundle?: Record<string, unknown>;
  /** Published doors whose bundle merges this card; publishing refreshes each. */
  doors_merging?: string[];
  /** objective -> entry node key, as the *graph* declares it (G-OB2's other half). */
  mission_entries?: Record<string, string>;
};

/**
 * Everything an Agent Studio write can invalidate, in one place.
 *
 * Two bugs came out of hand-rolling this per mutation, and both were the same
 * mistake — a key that reads like a prefix of the query it meant to refresh but
 * is not one:
 *
 * - Archive/restore invalidated `["agent-studio"]`, which does not reach the
 *   change log at `["agent-change-log", …]`. The tamper-evident record of the
 *   archive that just happened stayed stale for 30s while sitting on screen.
 * - Signing a skill invalidated `["agent-studio","skills"]`, which does not
 *   prefix-match the detail key `["agent-studio","skill",id]` — one character.
 *   So after the "Signed" toast the lozenge still read unsigned and the Sign
 *   button stayed enabled.
 *
 * `["agent-studio"]` covers cards, card, graph, skills, skill and templates
 * because they all descend from it. Every other root a studio mutation can
 * stale is listed here explicitly, so adding a mutation means calling this
 * rather than guessing.
 */
export function invalidateAgentStudio(qc: ReturnType<typeof useQueryClient>): void {
  void qc.invalidateQueries({ queryKey: ["agent-studio"] });
  void qc.invalidateQueries({ queryKey: ["agent-change-log"] });
  void qc.invalidateQueries({ queryKey: ["deployments"] });
  void qc.invalidateQueries({ queryKey: ["bot-deployments"] });
  void qc.invalidateQueries({ queryKey: ["roles"] });
  void qc.invalidateQueries({ queryKey: ["eval-reports"] });
  void qc.invalidateQueries({ queryKey: ["eval-suites"] });
  void qc.invalidateQueries({ queryKey: ["connectors"] });
  void qc.invalidateQueries({ queryKey: ["mcp-connectors"] });
  void qc.invalidateQueries({ queryKey: ["flow-tools"] });
  void qc.invalidateQueries({ queryKey: ["sandbox"] });
}

export function useAgentStudioCards(includeArchived = false) {
  return useQuery({
    queryKey: ["agent-studio", "cards", includeArchived],
    queryFn: async () =>
      apiGet<AgentCardSummary[]>(
        `/agent-studio/cards${includeArchived ? "?includeArchived=true" : ""}`,
      ),
  });
}

export function useArchiveAgentCard() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { botId: string; archived: boolean }) =>
      apiPost<{ ok: boolean; botId: string; archived: boolean }>(
        `/agent-studio/cards/${body.botId}/${body.archived ? "archive" : "restore"}`,
        {},
      ),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function useCompileCard(botId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body?: Record<string, unknown>) =>
      apiPost<CompileReport>(`/agent-studio/cards/${botId}/compile`, body ?? {}, {
        schema: compileReportSchema,
      }),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

/**
 * Read-only compile of a card the user is still editing.
 *
 * A query, not `useCompileCard`: that mutation invalidates the `agent-studio`
 * key on success, which would refetch the card the preview was derived from and
 * re-trigger the preview — a loop. Keyed on the payload, so an unchanged card
 * is served from cache rather than recompiled.
 */
export function useCompilePreview(botId: string, body: Record<string, unknown>, enabled = true) {
  // Debounced, and serialised key-order-independently.
  //
  // The card is a fresh object on every render of the editor, so keying on
  // `JSON.stringify` alone meant a new query key — and therefore a new POST to
  // a compiler that walks sixteen gates — for every keystroke in every field
  // the Tools, Skills and Outbound tabs feed into it. Typing a purpose sent one
  // compile per character.
  //
  // `stableStringify` on top of that, for the same reason the autosave
  // fingerprint needs it: a spread that rebuilds the card in a different key
  // order is not a different card, and must not cost a round trip.
  const key = stableStringify(body);
  const [debounced, setDebounced] = useState(key);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(key), 400);
    return () => window.clearTimeout(t);
  }, [key]);

  return useQuery({
    queryKey: ["agent-studio", "compile-preview", botId, debounced],
    // Compile what the key describes, not whatever `body` happens to be on the
    // render that wins the race — otherwise the cached result is filed under a
    // payload it was not computed from.
    queryFn: () =>
      apiPost<CompileReport>(
        `/agent-studio/cards/${botId}/compile`,
        JSON.parse(debounced) as Record<string, unknown>,
        { schema: compileReportSchema },
      ),
    enabled: enabled && Boolean(botId),
    staleTime: 30_000,
    retry: false,
  });
}

export function useEffectiveContract(botId: string, enabled = true) {
  return useQuery({
    queryKey: ["agent-studio", "effective-contract", botId],
    queryFn: () =>
      apiGet(`/agent-studio/cards/${botId}/effective-contract`, {
        schema: effectiveContractSchema,
      }),
    enabled: enabled && Boolean(botId),
    retry: retryUnlessClientError,
  });
}

export function useAgentStudioCard(botId: string) {
  return useQuery({
    queryKey: ["agent-studio", "card", botId],
    queryFn: async () => apiGet<AgentCardSummary>(`/agent-studio/cards/${botId}`),
    enabled: Boolean(botId),
    // `agent_card_not_found` is a settled answer about this id, and retrying it
    // three times is not free here: the studio decides whether to render an
    // editor at all from this query, so seven seconds of "still trying" was
    // seven seconds of a fully editable studio for a bot that does not exist.
    retry: retryUnlessClientError,
  });
}

export type AgentGraph = {
  botId: string;
  /** `reachability`/`deploymentStatus` mirror AgentCardSummary — the server
   *  has them already when it builds the node list, and the allowlist editor
   *  needs them to say whether a target takes traffic today. */
  nodes: {
    id: string;
    label: string;
    reachability?: AgentCardSummary["reachability"];
    deploymentStatus?: AgentCardSummary["deploymentStatus"];
  }[];
  /** `to` is null when a handoff row carries no target; the panel filters those. */
  edges: { from: string; to: string | null }[];
};

export function useAgentGraph(botId: string) {
  return useQuery({
    queryKey: ["agent-studio", "graph", botId],
    queryFn: async () => apiGet<AgentGraph>(`/agent-studio/cards/${botId}/graph`),
    enabled: Boolean(botId),
  });
}

export type EvalSuite = { id: string; kind: string; name: string; description: string };

/** One policy engine and the mode it runs in on this stack (GET /agent-studio/policy-engines). */
export type PolicyEngine = {
  key: string;
  label: string;
  tool: string | null;
  /** off | shadow | live, or "always" for an engine with no mode knob. */
  mode: string;
  source: string | null;
};

export function usePolicyEngines() {
  return useQuery({
    queryKey: ["agent-studio", "policy-engines"],
    queryFn: async () => {
      return apiGet<PolicyEngine[]>("/agent-studio/policy-engines");
    },
    staleTime: 60_000,
  });
}

export function useEvalSuites() {
  return useQuery({
    queryKey: ["eval-suites"],
    queryFn: async () => apiGet<EvalSuite[]>("/eval/suites"),
  });
}

/**
 * `botId` files the report against the card the run was launched from. Without
 * it the server guesses from the suite name, so a run started on a cloned card
 * landed under kaia-v2-4 and the tab that launched it still read "never run".
 */
export function useRunEvalSuite(botId?: string, promptVersionId?: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: async (suiteId: string) => {
      const q = new URLSearchParams();
      if (botId) q.set("botId", botId);
      if (promptVersionId) q.set("promptVersionId", promptVersionId);
      const suffix = q.toString() ? `?${q.toString()}` : "";
      return apiPost<{
        suiteId: string;
        status: string;
        failed: number;
        total: number;
        reportId?: string;
      }>(`/eval/suites/${suiteId}/run${suffix}`, {});
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["eval-suites"] });
      void qc.invalidateQueries({ queryKey: ["eval-reports"] });
      invalidateAgentStudio(qc);
    },
  });
}

export type EvalReport = {
  id: string;
  suiteId: string;
  suiteName?: string;
  kind?: string;
  botId?: string | null;
  status: string;
  summary: { failed?: number; total?: number; origin?: string };
  origin?: string;
  createdAt?: string | null;
};

/** One graded fixture behind a report's verdict. */
export type EvalTrial = {
  taskId?: string | null;
  name?: string | null;
  passed: boolean;
  verdict: { graders?: { grader?: string; passed?: boolean; detail?: string }[] };
  fixture: Record<string, unknown>;
};

export type EvalReportDetail = {
  id: string;
  status?: string | null;
  summary?: { failed?: number; total?: number } | null;
  trials: EvalTrial[];
};

/** The report with its trials, failed first -- fetched when a row is opened. */
export function useEvalReportDetail(reportId: string | null) {
  return useQuery({
    queryKey: ["eval-report", reportId],
    enabled: Boolean(reportId),
    queryFn: () => apiGet<EvalReportDetail>(`/eval/reports/${encodeURIComponent(reportId!)}`),
  });
}

/** `botId` that asks for the reports the scheduler filed against no card. */
export const TENANT_WIDE_REPORTS = "__none__";

export function useEvalReports(
  kind?: string,
  botId?: string,
  opts?: { limit?: number; perBot?: number },
) {
  return useQuery({
    queryKey: [
      "eval-reports",
      kind ?? "all",
      botId ?? "all",
      opts?.limit ?? null,
      opts?.perBot ?? null,
    ],
    queryFn: async () => {
      const q = new URLSearchParams();
      if (kind) q.set("kind", kind);
      if (botId) q.set("botId", botId);
      if (opts?.limit) q.set("limit", String(opts.limit));
      if (opts?.perBot) q.set("perBot", String(opts.perBot));
      const qs = q.toString();
      return apiGet<EvalReport[]>(`/eval/reports${qs ? `?${qs}` : ""}`);
    },
  });
}

export function useRunEvalSchedule() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: async () =>
      apiPost<{ status: string; ran: number; failed: number }>("/eval/schedule/run", {}),
    onSuccess: () => {
      invalidateAgentStudio(qc);
    },
  });
}

export type RolesCatalog = {
  permissions: { id: string; module: string; action: string; description: string }[];
  agentPublishRoles: string[];
  grants: { role: string; permission_id: string; role_id?: string }[];
  roles?: { id: string; name: string; permissionIds: string[] }[];
};

export type CloneTemplate = {
  id: string;
  label: string;
  sourceBotId: string;
  purpose: string;
};

export type DeploymentExperiment = {
  id: string;
  botId: string;
  trafficPct: number;
  shadow: boolean;
  autoRollback: string[];
  status: string;
  rollbackReason?: string | null;
  canaryDeploymentId?: string;
  baselineDeploymentId?: string | null;
};

export function useRolesCatalog() {
  return useQuery({
    queryKey: ["roles"],
    queryFn: async () => apiGet<RolesCatalog>("/roles"),
  });
}

export function usePatchRolePermissions() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { roleId: string; permissionIds: string[] }) =>
      apiPatch(`/roles/${body.roleId}/permissions`, { permissionIds: body.permissionIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["roles"] }),
  });
}

export function useAgentStudioTemplates() {
  return useQuery({
    queryKey: ["agent-studio", "templates"],
    queryFn: async () => apiGet<CloneTemplate[]>("/agent-studio/templates"),
  });
}

export function useCloneAgentCard() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { templateId: string; name?: string }) =>
      apiPost<AgentCardSummary>("/agent-studio/cards/clone", body),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function useDeploymentExperiments(botId: string) {
  return useQuery({
    queryKey: ["deployments", "experiments", botId],
    queryFn: async () =>
      apiGet<DeploymentExperiment[]>(
        `/bot-deployments/experiments?botId=${encodeURIComponent(botId)}`,
      ),
  });
}

/**
 * `baselineRestored` distinguishes the two outcomes this endpoint has.
 *
 * With a baseline deployment it retires the canary and reactivates the previous
 * one. Without a baseline it closes the experiment and reactivates nothing — the
 * canary keeps taking traffic. Both used to look identical from here.
 */
export type ExperimentRollbackResult = DeploymentExperiment & { baselineRestored: boolean };

export function useRollbackExperiment() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (experimentId: string) =>
      apiPost<ExperimentRollbackResult>(`/bot-deployments/experiments/${experimentId}/rollback`, {
        reason: "manual",
      }),
    onSuccess: () => {
      invalidateAgentStudio(qc);
    },
  });
}

// ---------------------------------------------------------------------------
// GET /agent-studio/change-log — the tamper-evident record of who changed what
// an agent says.
//
// Hash-chained per TENANT, and the verdict travels with the entries rather than
// on a separate call, because "a change log whose integrity you have to
// remember to check separately is one nobody checks". Note the asymmetry that
// follows from the chain being tenant-scoped: filtering by botId narrows
// `entries` but NOT `chain.checked`, so a card with no publishes still gets a
// verdict computed over every card in the tenant. The UI has to say which.
// ---------------------------------------------------------------------------

/** Which parts of a prompt bundle moved in a publish. */
export type ChangedComponent =
  "prompt" | "persona" | "voice" | "guardrails" | "flow" | "agent_card";

export type ChangeLogEntry = {
  id: string;
  actorUserId: string | null;
  action: "agent.publish" | "agent.rollback" | "agent.archive" | "agent.restore" | (string & {});
  botId: string | null;
  at: string | null;
  seq?: number;
  entryHash?: string;
  prevHash?: string;
  /** agent.publish only. */
  versionLabel?: string | null;
  previousVersionLabel?: string | null;
  versionId?: string | null;
  previousVersionId?: string | null;
  deploymentId?: string | null;
  summary?: string | null;
  changed?: ChangedComponent[];
  rollout?: { trafficPct: number; shadow: boolean; autoRollback: string[] };
  gates?: Record<string, string>;
  /** component -> sha256 of what shipped; what the entry hash is made of. */
  hashes?: Record<string, string>;
  /** agent.rollback / agent.archive. */
  replacedDeploymentId?: string | null;
  retiredDeploymentId?: string | null;
  /** agent.restore only — when the card was retired, so the gap is readable. */
  archivedAt?: string | null;
};

export type ChainVerdict = {
  ok: boolean;
  /** Rows walked. Tenant-wide, NOT the length of `entries`. */
  checked: number;
  brokenAt: string | null;
  /** "prev_hash_mismatch" | "entry_hash_mismatch", or null when intact. */
  reason: string | null;
};

export type ChangeLog = {
  entries: ChangeLogEntry[];
  chain: ChainVerdict;
  /** Entries matching the filter, before the limit. */
  total?: number;
};

export async function fetchChangeLog(botId?: string, limit = 50): Promise<ChangeLog> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (botId) q.set("botId", botId);
  return apiGet<ChangeLog>(`/agent-studio/change-log?${q.toString()}`);
}

export function useChangeLog(botId?: string, limit = 50) {
  return useQuery({
    queryKey: ["agent-change-log", botId ?? "tenant", limit],
    queryFn: () => fetchChangeLog(botId, limit),
    staleTime: 30_000,
  });
}

// ---------------------------------------------------------------------------
// LLM-judge critique — GET /eval/critiques, POST /eval/reports/{id}/critique.
//
// Reads failed eval trials and proposes a SKILL.md line. It never writes the
// skill: `writesProduction` is false on the row and false again inside the
// diff, and the module docstring says "Suggests a diff; never writes SKILL.md".
// The UI has to keep saying so, because a suggested diff that looks applied is
// the dangerous misreading of this screen.
//
// Both endpoints degrade rather than fail when the skill_critiques table is
// absent: the GET returns [], the POST 404s with "skill_critiques_missing".
// That 404 is a provisioning state, not an error, and reads differently.
// ---------------------------------------------------------------------------

export type SkillCritique = {
  id: string;
  skillSlug: string | null;
  reportId: string | null;
  suggestedDiff: {
    path?: string;
    op?: string;
    add?: string;
    grader?: string;
    writesProduction?: boolean;
  };
  status: string;
  writesProduction: boolean;
  createdAt: string | null;
};

export async function fetchSkillCritiques(limit = 50): Promise<SkillCritique[]> {
  return apiGet<SkillCritique[]>(`/eval/critiques?limit=${limit}`);
}

export function useSkillCritiques(limit = 50) {
  return useQuery({
    queryKey: ["eval-critiques", limit],
    queryFn: () => fetchSkillCritiques(limit),
    staleTime: 30_000,
  });
}

export function useCritiqueReport() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (reportId: string) => {
      return apiPost<SkillCritique[]>(`/eval/reports/${encodeURIComponent(reportId)}/critique`, {});
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["eval-critiques"] });
    },
  });
}

// ---------------------------------------------------------------------------
// GET /eval/disagreements — where the auto-scorer and a human disagreed.
//
// Only the two contradictions that matter are mined: live QA passed a call
// humans scored red, or barged a call humans scored green. Read-only by
// construction — `applied` is false on the envelope and on every item, and the
// module says "Rubric tweaks only" / "this never writes the rubric".
// ---------------------------------------------------------------------------

export type QaDisagreement = {
  interactionId: string | null;
  liveVerdict: string;
  humanBand: string;
  humanScore: number | null;
  suggestedRubricTweak: string;
  applied: boolean;
};

export type QaDisagreements = {
  applied: boolean;
  count: number;
  items: QaDisagreement[];
};

export async function fetchQaDisagreements(limit = 50): Promise<QaDisagreements> {
  return apiGet<QaDisagreements>(`/eval/disagreements?limit=${limit}`);
}

export function useQaDisagreements(limit = 50) {
  return useQuery({
    queryKey: ["eval-disagreements", limit],
    queryFn: () => fetchQaDisagreements(limit),
    staleTime: 60_000,
  });
}
