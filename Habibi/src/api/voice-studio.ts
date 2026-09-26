// -----------------------------------------------------------------------------
// PayInt Voice Studio — what PayInt keeps per engine agent.
//   Agents:     GET /studio-api/workflow/summary (through the RBAC gateway)
//   Guardrails: GET/PUT /voice-studio/guardrails/{workflowId}
//   Checks:     GET/POST /voice-studio/checks (scripted rehearsals, graded)
//   Releases:   GET  /voice-studio/agents/{id}/preflight, POST .../publish,
//               POST .../rollback, GET /voice-studio/releases (changelog)
// -----------------------------------------------------------------------------

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, apiPut } from "./config";

export interface StudioAgent {
  id: number;
  name: string;
}

export function useStudioAgents({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    enabled,
    queryKey: ["voice-studio", "agents"],
    queryFn: () => apiGet<StudioAgent[]>("/studio-api/workflow/summary?status=active"),
  });
}

export type StudioChannel = "inbound" | "outbound" | "whatsapp";

export interface StudioRouting {
  agents: StudioAgent[];
  bindings: { objective: string; engine_workflow_id: number; label: string | null }[];
  numbers: {
    id: number;
    configId: number;
    label: string;
    addressMasked: string;
    workflowId: number | null;
    active: boolean;
  }[];
}

export interface RoutingCheck {
  ok: boolean;
  errors: string[];
  warnings?: string[];
  workflowId: number;
  name: string;
  definitionId: number;
  version: number;
  toolUuids: string[];
}

export interface RoutingChoice {
  channel: StudioChannel;
  workflowId: number;
  objective?: string;
  configId?: number;
  phoneId?: number;
}

export function useStudioRouting() {
  return useQuery({
    queryKey: ["voice-studio", "routing"],
    queryFn: () => apiGet<StudioRouting>("/voice-studio/routing"),
  });
}

export function useCheckRouting() {
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (choice: RoutingChoice) =>
      apiPost<RoutingCheck>("/voice-studio/routing/check", choice),
  });
}

export function useAssignRouting() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (choice: RoutingChoice) =>
      apiPut<{ workflowId: number; definitionId: number }>("/voice-studio/routing", choice),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["voice-studio", "routing"] }),
  });
}

export interface Guardrails {
  prohibited: string[];
  escalateAbuse: boolean;
  escalateLegal: boolean;
  neverQuoteRate: boolean;
  neverPromiseWaiver: boolean;
  alwaysDiscloseRecording: boolean;
  refusePoliticsReligion: boolean;
  maxTurns: number;
}

interface GuardrailsResponse {
  workflowId: number;
  guardrails: Guardrails;
  defaults: Guardrails;
}

export function useAgentGuardrails(workflowId: number | null) {
  return useQuery({
    queryKey: ["voice-studio", "guardrails", workflowId],
    queryFn: () => apiGet<GuardrailsResponse>(`/voice-studio/guardrails/${workflowId}`),
    enabled: workflowId !== null,
  });
}

export function useSaveGuardrails(workflowId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (guardrails: Guardrails) =>
      apiPut<GuardrailsResponse>(`/voice-studio/guardrails/${workflowId}`, { guardrails }),
    onSuccess: (data) => qc.setQueryData(["voice-studio", "guardrails", workflowId], data),
  });
}

export interface CheckScenario {
  id: string;
  name: string;
  turns: string[];
}

export interface CheckTurn {
  customer: string;
  agent: string;
  flags: string[];
}

export interface CheckResult {
  scenarioId: string;
  scenarioName: string;
  workflowRunId: number | null;
  turns: CheckTurn[];
  flags: string[];
  passed: boolean;
  error?: string | null;
}

export interface CheckRun {
  id: string;
  workflowId: number;
  createdAt: string;
  createdBy: string | null;
  status: "running" | "done";
  passed: number;
  failed: number;
  results: CheckResult[];
}

export function useCheckScenarios() {
  return useQuery({
    queryKey: ["voice-studio", "check-scenarios"],
    queryFn: () => apiGet<CheckScenario[]>("/voice-studio/checks/scenarios"),
  });
}

export function useCheckRuns(workflowId: number | null) {
  return useQuery({
    queryKey: ["voice-studio", "checks", workflowId],
    queryFn: () => apiGet<CheckRun[]>(`/voice-studio/checks?workflowId=${workflowId}`),
    enabled: workflowId !== null,
    // A run takes about a minute; poll only while one is still going.
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "running") ? 5000 : false),
  });
}

export function useRunChecks(workflowId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (scenarioIds: string[]) =>
      apiPost<CheckRun>("/voice-studio/checks", { workflowId, scenarioIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["voice-studio", "checks", workflowId] }),
  });
}

export interface ReleasePreflight {
  ok: boolean;
  errors: string[];
  channels: string[];
  draftVersion: number | null;
  liveVersion: number | null;
  liveVersionId: number | null;
  lastCheck: {
    status: "running" | "done";
    passed: number;
    failed: number;
    createdAt: string;
  } | null;
}

export interface Release {
  id: string;
  workflowId: number;
  version: number | null;
  fromVersion: number | null;
  action: "publish" | "rollback";
  note: string;
  actor: string | null;
  createdAt: string;
}

const releasesKey = (workflowId: number | null) =>
  ["voice-studio", "releases", workflowId] as const;

export function useReleasePreflight(workflowId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["voice-studio", "preflight", workflowId],
    queryFn: () => apiGet<ReleasePreflight>(`/voice-studio/agents/${workflowId}/preflight`),
    enabled,
    // The draft changes between openings of the dialog; always re-check.
    staleTime: 0,
  });
}

export function useReleases(workflowId: number | null, limit = 50) {
  return useQuery({
    queryKey: [...releasesKey(workflowId), limit],
    queryFn: () =>
      apiGet<Release[]>(
        `/voice-studio/releases?limit=${limit}${workflowId === null ? "" : `&workflowId=${workflowId}`}`,
      ),
  });
}

function useReleaseMutation<V>(workflowId: number, action: "publish" | "rollback") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: V) => apiPost<Release>(`/voice-studio/agents/${workflowId}/${action}`, body),
    // The publish and rollback dialogs toast the server's reason themselves.
    meta: { errors: "caller" },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["voice-studio", "releases"] });
      void qc.invalidateQueries({ queryKey: ["voice-studio", "preflight", workflowId] });
    },
  });
}

export function usePublishAgent(workflowId: number) {
  return useReleaseMutation<{ note: string }>(workflowId, "publish");
}

export function useRollbackAgent(workflowId: number) {
  return useReleaseMutation<{ versionId: number; note: string }>(workflowId, "rollback");
}

export interface PromptFinding {
  severity: "error" | "warn" | "info";
  code: string;
  message: string;
  span: { start: number; end: number } | null;
}

export interface PromptLintResult {
  findings: PromptFinding[];
  tokens: number;
  usdPerTurn: number;
}

/** Lint of a node prompt as the engine renders it; `prompt` should already be debounced. */
export function usePromptLint(
  prompt: string,
  workflowId: number | null,
  isOpening: boolean,
  greeting = "",
) {
  return useQuery({
    queryKey: ["voice-studio", "prompt-lint", workflowId, isOpening, prompt, greeting],
    queryFn: () =>
      apiPost<PromptLintResult>("/voice-studio/prompt/lint", {
        prompt,
        workflowId,
        isOpening,
        greeting,
      }),
    enabled: prompt.trim().length > 0,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

/** An AI customer described in plain words talks to the agent; the run is graded like a check. */
export function useSimulateCustomer(workflowId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (persona: string) =>
      apiPost<{ id: string; status: "running" }>("/voice-studio/checks/simulate", {
        workflowId,
        persona,
      }),
    meta: { errors: "caller" },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["voice-studio", "checks", workflowId] }),
  });
}
