import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiGetBlob, apiPatch, apiPost, apiUpload, USE_MOCK } from "./config";

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
   * Routing, not deployment. `entry` takes inbound calls/messages; `handoff` is
   * in the transitive closure of the entry card's handoff allowlist; everything
   * else is deployed but unreachable.
   */
  reachability: "entry" | "handoff" | "unreachable" | "archived";
  archivedAt: string | null;
  /** Re-seeded on API boot, so it can never be archived. */
  isFirstParty: boolean;
  /** The editable card (draft when one exists). */
  agentCard: Record<string, unknown>;
  /** What production is actually running. Empty until first publish. */
  publishedCard: Record<string, unknown>;
};

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
  card: Record<string, unknown>;
};

const MOCK_CARDS: AgentCardSummary[] = [
  {
    botId: "intake-v1",
    name: "Intake",
    version: "1.0",
    slug: "intake",
    purpose: "Identify the caller and route.",
    channels: ["voice", "whatsapp"],
    skills: ["verify-and-disclose"],
    toolCount: 6,
    evalStatus: "skipped",
    trafficPct: 100,
    deploymentStatus: "live",
    draftVersionId: null,
    hasDraft: false,
    cardSource: "published",
    entryBotId: "kaia-v2-4",
    reachability: "handoff",
    archivedAt: null,
    isFirstParty: true,
    lastPublish: null,
    promptVersionId: "pv-intake-1",
    agentCard: {},
    publishedCard: {},
  },
  {
    botId: "kaia-v2-4",
    name: "Collections",
    version: "2.4",
    slug: "collections",
    purpose: "Recover overdue balances.",
    channels: ["voice", "whatsapp"],
    skills: [
      "verify-and-disclose",
      "ptp-negotiate",
      "hardship-intake",
      "dispute-capture",
      "doc-fulfil",
      "broken-ptp-chase",
      "upsell-pitch",
      "floor-coach",
    ],
    toolCount: 16,
    evalStatus: "skipped",
    trafficPct: 100,
    deploymentStatus: "live",
    draftVersionId: null,
    hasDraft: false,
    cardSource: "published",
    entryBotId: "kaia-v2-4",
    reachability: "handoff",
    archivedAt: null,
    isFirstParty: true,
    lastPublish: null,
    promptVersionId: "v1_4",
    agentCard: {},
    publishedCard: {},
  },
  {
    botId: "insurance-v1",
    name: "Insurance",
    version: "1.0",
    slug: "insurance",
    purpose: "Eligibility and lead capture.",
    channels: ["voice", "whatsapp"],
    skills: ["verify-and-disclose", "insurance-lapse", "doc-fulfil"],
    toolCount: 8,
    evalStatus: "skipped",
    trafficPct: 100,
    deploymentStatus: "live",
    draftVersionId: null,
    hasDraft: false,
    cardSource: "published",
    entryBotId: "kaia-v2-4",
    reachability: "handoff",
    archivedAt: null,
    isFirstParty: true,
    lastPublish: null,
    promptVersionId: "pv-insurance-1",
    agentCard: {},
    publishedCard: {},
  },
  {
    botId: "supervisor-brief",
    name: "Supervisor brief",
    version: "1.0",
    slug: "supervisor_brief",
    purpose: "Warm-transfer brief.",
    channels: ["internal"],
    skills: ["supervisor-brief", "qa-examiner"],
    toolCount: 0,
    evalStatus: "skipped",
    trafficPct: 100,
    deploymentStatus: "live",
    draftVersionId: null,
    hasDraft: false,
    cardSource: "published",
    entryBotId: "kaia-v2-4",
    reachability: "handoff",
    archivedAt: null,
    isFirstParty: true,
    lastPublish: null,
    promptVersionId: "pv-supervisor-1",
    agentCard: {},
    publishedCard: {},
  },
];

export function useAgentStudioCards(includeArchived = false) {
  return useQuery({
    queryKey: ["agent-studio", "cards", includeArchived],
    queryFn: async () =>
      USE_MOCK
        ? MOCK_CARDS
        : apiGet<AgentCardSummary[]>(
            `/agent-studio/cards${includeArchived ? "?includeArchived=true" : ""}`,
          ),
  });
}

export function useArchiveAgentCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { botId: string; archived: boolean }) =>
      apiPost<{ ok: boolean; botId: string; archived: boolean }>(
        `/agent-studio/cards/${body.botId}/${body.archived ? "archive" : "restore"}`,
        {},
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function useCompileCard(botId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body?: Record<string, unknown>) =>
      apiPost<CompileReport>(`/agent-studio/cards/${botId}/compile`, body ?? {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
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
export function useCompilePreview(
  botId: string,
  body: Record<string, unknown>,
  enabled = true,
) {
  const payload = JSON.stringify(body);
  return useQuery({
    queryKey: ["agent-studio", "compile-preview", botId, payload],
    queryFn: () => apiPost<CompileReport>(`/agent-studio/cards/${botId}/compile`, body),
    enabled: enabled && Boolean(botId),
    staleTime: 30_000,
    retry: false,
  });
}

export function usePatchAgentCard(botId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (agentCard: Record<string, unknown>) =>
      apiPatch(`/agent-studio/cards/${botId}`, { agentCard }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function useAgentStudioCard(botId: string) {
  return useQuery({
    queryKey: ["agent-studio", "card", botId],
    queryFn: async () =>
      USE_MOCK
        ? MOCK_CARDS.find((c) => c.botId === botId) ?? null
        : apiGet<AgentCardSummary>(`/agent-studio/cards/${botId}`),
    enabled: Boolean(botId),
  });
}

export type AgentGraph = {
  botId: string;
  nodes: { id: string; label: string }[];
  edges: { from: string; to: string }[];
};

export function useAgentGraph(botId: string) {
  return useQuery({
    queryKey: ["agent-studio", "graph", botId],
    queryFn: async () =>
      USE_MOCK
        ? {
            botId,
            nodes: MOCK_CARDS.map((c) => ({ id: c.botId, label: c.name })),
            edges: [{ from: botId, to: "insurance-v1" }],
          }
        : apiGet<AgentGraph>(`/agent-studio/cards/${botId}/graph`),
    enabled: Boolean(botId),
  });
}

export type EvalSuite = { id: string; kind: string; name: string; description: string };

export function useEvalSuites() {
  return useQuery({
    queryKey: ["eval-suites"],
    queryFn: async () =>
      USE_MOCK
        ? [
            {
              id: "eval-regression-collections",
              kind: "regression",
              name: "Collections regression",
              description: "code graders",
            },
          ]
        : apiGet<EvalSuite[]>("/eval/suites"),
  });
}

/**
 * `botId` files the report against the card the run was launched from. Without
 * it the server guesses from the suite name, so a run started on a cloned card
 * landed under kaia-v2-4 and the tab that launched it still read "never run".
 */
export function useRunEvalSuite(botId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (suiteId: string) =>
      apiPost<{ suiteId: string; status: string; failed: number; total: number; reportId?: string }>(
        `/eval/suites/${suiteId}/run${botId ? `?botId=${encodeURIComponent(botId)}` : ""}`,
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["eval-suites"] });
      void qc.invalidateQueries({ queryKey: ["eval-reports"] });
      void qc.invalidateQueries({ queryKey: ["agent-studio"] });
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

export function useEvalReports(kind?: string, botId?: string) {
  return useQuery({
    queryKey: ["eval-reports", kind ?? "all", botId ?? "all"],
    queryFn: async () => {
      if (USE_MOCK) {
        return [
          {
            id: "EVR-mock",
            suiteId: "eval-regression-collections",
            suiteName: "Collections regression",
            kind: "regression",
            status: "pass",
            summary: { failed: 0, total: 6 },
            origin: "scheduled",
            createdAt: new Date().toISOString(),
          },
        ] satisfies EvalReport[];
      }
      const q = new URLSearchParams();
      if (kind) q.set("kind", kind);
      if (botId) q.set("botId", botId);
      const qs = q.toString();
      return apiGet<EvalReport[]>(`/eval/reports${qs ? `?${qs}` : ""}`);
    },
    staleTime: 15_000,
  });
}

export function useRunEvalSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      apiPost<{ status: string; ran: number; failed: number }>("/eval/schedule/run", {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["eval-reports"] });
      void qc.invalidateQueries({ queryKey: ["eval-suites"] });
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

export type SkillSummary = {
  id: string;
  slug: string;
  origin: string;
  signatureStatus: string;
  description: string;
  allowedTools: string[];
  version: string;
  status: string;
  attachedCards: string[];
  signed: boolean;
  hasSignedVersion?: boolean;
  latestVersionId?: string;
  versions?: Array<{ id: string; version: string; status: string }>;
  body?: string;
  frontmatter?: Record<string, unknown>;
  markdown?: string;
  pack?: { references?: Record<string, string> };
  bodyTokens?: number;
  referenceFiles?: string[];
};

const MOCK_SKILLS: SkillSummary[] = [
  {
    id: "skill-verify-and-disclose",
    slug: "verify-and-disclose",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Verify the caller and disclose recording before any account fact.",
    allowedTools: ["verify_identity", "get_customer_context", "add_customer_note"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4", "intake-v1", "insurance-v1"],
    signed: true,
    bodyTokens: 180,
  },
  {
    id: "skill-ptp-negotiate",
    slug: "ptp-negotiate",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Negotiate a Promise-to-Pay. Authority decides the cap; DND blocks writes outside the calling window.",
    allowedTools: ["create_promise_to_pay", "evaluate_authority", "run_skill_script"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4"],
    signed: true,
    bodyTokens: 220,
  },
  {
    id: "skill-hardship-intake",
    slug: "hardship-intake",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Capture hardship. Write a note, hold treatment, do not pitch a product.",
    allowedTools: ["add_customer_note", "escalate_to_human", "request_callback"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4"],
    signed: true,
    bodyTokens: 160,
  },
  {
    id: "skill-dispute-capture",
    slug: "dispute-capture",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Record a dispute. Call flag_dispute. Do not negotiate PTP on a live dispute.",
    allowedTools: ["flag_dispute", "add_customer_note", "escalate_to_human"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4"],
    signed: true,
    bodyTokens: 140,
  },
  {
    id: "skill-doc-fulfil",
    slug: "doc-fulfil",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Raise a document request for a verified customer.",
    allowedTools: ["request_documents", "get_customer_context"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4", "insurance-v1"],
    signed: true,
    bodyTokens: 90,
  },
  {
    id: "skill-broken-ptp-chase",
    slug: "broken-ptp-chase",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Follow up a broken promise. Respect attempt caps. Do not write a new PTP.",
    allowedTools: ["request_callback", "add_customer_note", "get_customer_context"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4"],
    signed: true,
    bodyTokens: 110,
  },
  {
    id: "skill-upsell-pitch",
    slug: "upsell-pitch",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Speak one reco-engine product after the primary query is resolved.",
    allowedTools: ["recommend_next_offer", "check_product_eligibility", "capture_lead", "decline_offer"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4"],
    signed: true,
    bodyTokens: 130,
  },
  {
    id: "skill-insurance-lapse",
    slug: "insurance-lapse",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Handle insurance lapse. Reco picks the product. Capture a lead after consent.",
    allowedTools: ["recommend_next_offer", "check_product_eligibility", "capture_lead", "request_documents"],
    version: "1",
    status: "signed",
    attachedCards: ["insurance-v1"],
    signed: true,
    bodyTokens: 120,
  },
  {
    id: "skill-qa-examiner",
    slug: "qa-examiner",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Internal live-QA examiner. Never speak to the customer.",
    allowedTools: ["add_customer_note"],
    version: "1",
    status: "signed",
    attachedCards: ["supervisor-brief"],
    signed: true,
    bodyTokens: 70,
  },
  {
    id: "skill-floor-coach",
    slug: "floor-coach",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Internal floor coach. Whisper or barge. Never take over money writes.",
    allowedTools: ["add_customer_note"],
    version: "1",
    status: "signed",
    attachedCards: ["kaia-v2-4"],
    signed: true,
    bodyTokens: 80,
  },
  {
    id: "skill-supervisor-brief",
    slug: "supervisor-brief",
    origin: "first_party",
    signatureStatus: "signed",
    description: "Compact warm-transfer brief. No CRM writes.",
    allowedTools: [],
    version: "1",
    status: "signed",
    attachedCards: ["supervisor-brief"],
    signed: true,
    bodyTokens: 60,
  },
];

export function useAgentStudioSkills() {
  return useQuery({
    queryKey: ["agent-studio", "skills"],
    queryFn: async () => (USE_MOCK ? MOCK_SKILLS : apiGet<SkillSummary[]>("/agent-studio/skills")),
  });
}

export function useAgentStudioSkill(skillId: string) {
  return useQuery({
    queryKey: ["agent-studio", "skill", skillId],
    queryFn: async () =>
      USE_MOCK
        ? MOCK_SKILLS.find((s) => s.id === skillId || s.slug === skillId) ?? null
        : apiGet<SkillSummary>(`/agent-studio/skills/${skillId}`),
    enabled: Boolean(skillId),
  });
}

export function useCreateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      slug: string;
      description?: string;
      allowedTools?: string[];
      body?: string;
    }) => apiPost<SkillSummary>("/agent-studio/skills", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio", "skills"] }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (skillId: string) =>
      apiDelete<{ ok: boolean; id: string; slug: string }>(`/agent-studio/skills/${skillId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function useSkillScripts() {
  return useQuery({
    queryKey: ["agent-studio", "skill-scripts"],
    queryFn: async () =>
      USE_MOCK
        ? [{ name: "emi_remaining" }, { name: "promise_date_in_window" }]
        : apiGet<{ name: string }[]>("/agent-studio/skills/scripts"),
    staleTime: 5 * 60_000,
  });
}

export function useSignSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (skillId: string) => apiPost(`/agent-studio/skills/${skillId}/sign`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio", "skills"] }),
  });
}

export function useRevertSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { skillId: string; versionId?: string }) =>
      apiPost(`/agent-studio/skills/${body.skillId}/revert`, { versionId: body.versionId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function usePatchSkill(skillId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) => apiPatch(`/agent-studio/skills/${skillId}`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function useRunSkillScript() {
  return useMutation({
    mutationFn: async (body: { name: string; payload: Record<string, unknown> }) =>
      apiPost<{ ok: boolean; error?: string } & Record<string, unknown>>("/agent-studio/skills/run-script", body),
  });
}

export async function exportSkillZip(skillId: string): Promise<void> {
  const { blob, headers } = await apiGetBlob(`/agent-studio/skills/${skillId}/export`);
  const disposition = headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] || `${skillId}.zip`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function importSkillZip(file: File): Promise<SkillSummary> {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<SkillSummary>("/agent-studio/skills/import", form);
}

export function useRolesCatalog() {
  return useQuery({
    queryKey: ["roles"],
    queryFn: async () =>
      USE_MOCK
        ? {
            permissions: [
              { id: "perm-agent-publish", module: "agent", action: "publish", description: "Compile and publish" },
            ],
            agentPublishRoles: ["Admin"],
            grants: [],
            roles: [{ id: "role-admin", name: "Admin", permissionIds: ["perm-agent-publish"] }],
          }
        : apiGet<RolesCatalog>("/roles"),
  });
}

export function usePatchRolePermissions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { roleId: string; permissionIds: string[] }) =>
      apiPatch(`/roles/${body.roleId}/permissions`, { permissionIds: body.permissionIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["roles"] }),
  });
}

export function useAgentStudioTemplates() {
  return useQuery({
    queryKey: ["agent-studio", "templates"],
    queryFn: async () =>
      USE_MOCK
        ? ([
            { id: "collections", label: "Collections", sourceBotId: "kaia-v2-4", purpose: "Recover overdue balances." },
            { id: "lapse", label: "Lapse Specialist", sourceBotId: "insurance-v1", purpose: "Premium lapse." },
            { id: "hardship", label: "Hardship", sourceBotId: "kaia-v2-4", purpose: "Hold treatment." },
            { id: "clerk", label: "Clerk", sourceBotId: "supervisor-brief", purpose: "Internal chase." },
          ] satisfies CloneTemplate[])
        : apiGet<CloneTemplate[]>("/agent-studio/templates"),
  });
}

export function useCloneAgentCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { templateId: string; name?: string }) =>
      apiPost<AgentCardSummary>("/agent-studio/cards/clone", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function useCloneSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { skillId: string; slug: string }) =>
      apiPost(`/agent-studio/skills/${body.skillId}/clone`, { slug: body.slug }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio", "skills"] }),
  });
}

export function useAttachConnector(botId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { connectorId: string; allowPrefixes?: string[] }) =>
      apiPost(`/agent-studio/cards/${botId}/connectors`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-studio"] }),
  });
}

export function useDeploymentExperiments(botId: string) {
  return useQuery({
    queryKey: ["deployments", "experiments", botId],
    queryFn: async () =>
      USE_MOCK ? [] : apiGet<DeploymentExperiment[]>(`/bot-deployments/experiments?botId=${encodeURIComponent(botId)}`),
  });
}

export function useRollbackExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (experimentId: string) =>
      apiPost(`/bot-deployments/experiments/${experimentId}/rollback`, { reason: "manual" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["deployments"] });
      void qc.invalidateQueries({ queryKey: ["agent-studio"] });
    },
  });
}
