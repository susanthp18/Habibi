// Integrations & API Connections — env-backed provider health (no secret writeback).
// Mock: seed catalog (secrets stripped). Live: GET /providers + enable/test.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  LIVE_PROVIDER_IDS,
  PROVIDERS,
  runMockHealthCheck,
  type Env,
  type Provider,
  type ProviderId,
  type TestLogEntry,
} from "@/data/integrations-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";

function mockProviders(): Provider[] {
  // Keep full catalog in mock; secrets already placeholders.
  return PROVIDERS.map((p) => ({
    ...p,
    perEnv: {
      sandbox: { ...p.perEnv.sandbox, credentialsLocked: false },
      production: { ...p.perEnv.production, credentialsLocked: false },
    },
  }));
}

export async function fetchProviders(env: Env = "sandbox"): Promise<Provider[]> {
  if (USE_MOCK) return mockDelay(mockProviders());
  const list = await apiGet<Provider[]>(`/providers?env=${encodeURIComponent(env)}`);
  // Live API returns stack providers only.
  return list.filter((p) => (LIVE_PROVIDER_IDS as readonly string[]).includes(p.id));
}

export function useProviders(env: Env) {
  return useQuery({
    queryKey: ["providers", env],
    queryFn: () => fetchProviders(env),
    staleTime: 15_000,
  });
}

export async function setProviderEnabled(
  providerId: ProviderId,
  env: Env,
  enabled: boolean,
): Promise<Provider> {
  if (USE_MOCK) {
    await mockDelay(undefined);
    const p = PROVIDERS.find((x) => x.id === providerId);
    if (!p) throw new Error("provider_not_found");
    const next: Provider = {
      ...p,
      perEnv: {
        ...p.perEnv,
        [env]: {
          ...p.perEnv[env],
          enabled,
          health: enabled
            ? p.perEnv[env].health === "unconfigured"
              ? "healthy"
              : p.perEnv[env].health
            : "unconfigured",
        },
      },
    };
    const idx = PROVIDERS.findIndex((x) => x.id === providerId);
    if (idx >= 0) PROVIDERS[idx] = next;
    return next;
  }
  return apiPatch<Provider>(`/providers/${providerId}/configs/${env}`, { enabled });
}

export async function testProviderConnection(
  provider: Provider,
  env: Env,
): Promise<TestLogEntry> {
  if (USE_MOCK) return runMockHealthCheck(provider, env);
  return apiPost<TestLogEntry>(
    `/providers/${provider.id}/test?env=${encodeURIComponent(env)}`,
    {},
  );
}

export async function fetchProviderTestLogs(providerId: ProviderId): Promise<TestLogEntry[]> {
  if (USE_MOCK) return mockDelay([]);
  return apiGet<TestLogEntry[]>(`/providers/${providerId}/test-logs`);
}

export function useProviderMutations(env: Env) {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["providers", env] });
  return {
    setEnabled: useMutation({
      mutationFn: (input: { id: ProviderId; enabled: boolean }) =>
        setProviderEnabled(input.id, env, input.enabled),
      onSuccess: invalidate,
    }),
    testOne: useMutation({
      mutationFn: (p: Provider) => testProviderConnection(p, env),
      onSuccess: invalidate,
    }),
  };
}

export type Connector = {
  id: string;
  slug: string;
  displayName: string;
  kind: "first_party" | "remote_mcp";
  url?: string | null;
  authRef?: string | null;
  allowPrefixes: string[];
  dataClass: string[];
  ttlMs?: number;
  timeoutMs?: number;
  allowedEnv?: string;
  status: "draft" | "approved" | "disabled";
  health: "unknown" | "healthy" | "degraded" | "down";
  lastToolsListAt?: string | null;
  toolsCache?: { name?: string }[];
  cimdIssuer?: string | null;
  cimdClientId?: string | null;
};

export type VaultRef = {
  id: string;
  name: string;
  purpose: string;
  backend: string;
  azureSecretName?: string | null;
  lastRotatedAt?: string | null;
  lastUsedAt?: string | null;
  hasSecret?: boolean;
};

export type McpKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  revoked: boolean;
  lastUsedAt?: string | null;
  createdAt?: string | null;
  key?: string;
};

export type McpTask = {
  id: string;
  kind: string;
  status: string;
  customerId?: string | null;
  say?: string;
  createdAt?: string | null;
};

export type McpStatus = {
  stdioCommand: string;
  httpEnabled: boolean;
  httpUrl: string;
  tasksEnabled: boolean;
  appsEnabled: boolean;
  mtls: boolean;
  resources: string[];
};

export type A2aPartner = {
  id: string;
  name: string;
  cardUrl: string | null;
  certFingerprint: string;
  certDn: string | null;
  allowedSkills: string[];
  status: string;
};

export type A2aTask = {
  id: string;
  partnerId?: string | null;
  botId?: string | null;
  skillId?: string | null;
  status: string;
  certDn?: string | null;
  createdAt?: string | null;
};

export type GatewayProfile = {
  capInr: number;
  model?: string | null;
  envModel?: string | null;
  canaryModel?: string | null;
};

export type GatewayCanary = {
  id: string;
  candidateModel: string;
  stage: "analysis" | "text" | "voice";
  status: string;
  injectionClosed?: boolean;
  voiceSloMs?: number | null;
  copyToEnv?: { name: string; value: string }[];
  appliedEnv?: boolean;
  gates?: {
    regression?: boolean;
    redteam?: boolean;
    twin?: boolean;
    injectionClosed?: boolean;
    voiceSloOk?: boolean;
    voiceSloMs?: number | null;
    budgetMs?: number;
  };
};

export type GatewayStatus = {
  enabled: boolean;
  baseUrl?: string | null;
  profiles: Record<string, GatewayProfile>;
  canary?: GatewayCanary | null;
  killSwitch?: string | null;
  voiceSloMs?: number;
};

const MOCK_CONNECTORS: Connector[] = [
  {
    id: "conn-paylink",
    slug: "paylink",
    displayName: "Pay-link status",
    kind: "first_party",
    allowPrefixes: ["ext.paylink."],
    dataClass: ["money", "pii"],
    status: "approved",
    health: "healthy",
    timeoutMs: 2500,
    allowedEnv: "both",
  },
  {
    id: "conn-lms",
    slug: "lms",
    displayName: "LMS balance",
    kind: "first_party",
    allowPrefixes: ["ext.lms."],
    dataClass: ["money", "pii"],
    status: "approved",
    health: "healthy",
    timeoutMs: 2500,
    allowedEnv: "both",
  },
];

const MOCK_MCP_STATUS: McpStatus = {
  stdioCommand: "python -m mcp_server",
  httpEnabled: false,
  httpUrl: "http://127.0.0.1:8081/mcp",
  tasksEnabled: false,
  appsEnabled: false,
  mtls: false,
  resources: [
    "customer://{id}",
    "account://{id}/ledger",
    "kb://snapshot/{id}",
    "interaction://{id}/trace",
    "policy://authority-matrix",
  ],
};

const MOCK_GATEWAY: GatewayStatus = {
  enabled: false,
  baseUrl: null,
  profiles: {
    voice: { capInr: 0, model: null },
    text: { capInr: 0, model: null },
    analysis: { capInr: 0, model: null },
    internal: { capInr: 0, model: null },
  },
  killSwitch: "azure_openai",
  canary: null,
  voiceSloMs: 800,
};

export function useConnectors() {
  return useQuery({
    queryKey: ["connectors"],
    queryFn: async () => (USE_MOCK ? mockDelay(MOCK_CONNECTORS) : apiGet<Connector[]>("/connectors")),
    staleTime: 15_000,
  });
}

export function useConnectorMutations() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["connectors"] });
  return {
    upsert: useMutation({
      mutationFn: (payload: Record<string, unknown>) =>
        USE_MOCK ? mockDelay(payload as Connector) : apiPost<Connector>("/connectors", payload),
      onSuccess: invalidate,
    }),
    approve: useMutation({
      mutationFn: (id: string) =>
        USE_MOCK ? mockDelay({ ok: true }) : apiPost(`/connectors/${id}/approve`, {}),
      onSuccess: invalidate,
    }),
    test: useMutation({
      mutationFn: (id: string) =>
        USE_MOCK ? mockDelay({ ok: true, kind: "first_party" }) : apiPost(`/connectors/${id}/test`, {}),
      onSuccess: invalidate,
    }),
    cimd: useMutation({
      mutationFn: (input: { id: string; issuer: string }) =>
        USE_MOCK
          ? mockDelay({ ok: true, clientId: "cimd-mock", issuer: input.issuer })
          : apiPost(`/connectors/${input.id}/cimd`, { issuer: input.issuer }),
      onSuccess: invalidate,
    }),
  };
}

export function useVaultRefs() {
  return useQuery({
    queryKey: ["vault-refs"],
    queryFn: async () => (USE_MOCK ? mockDelay([] as VaultRef[]) : apiGet<VaultRef[]>("/vault/refs")),
    staleTime: 15_000,
  });
}

export function useVaultMutations() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["vault-refs"] });
  return {
    put: useMutation({
      mutationFn: (payload: { name: string; purpose: string; secret: string }) =>
        USE_MOCK
          ? mockDelay({
              id: `vault-mock`,
              name: payload.name,
              purpose: payload.purpose,
              backend: "local",
              hasSecret: true,
            } satisfies VaultRef)
          : apiPost<VaultRef>("/vault/refs", payload),
      onSuccess: invalidate,
    }),
    rotate: useMutation({
      mutationFn: (input: { id: string; secret: string }) =>
        USE_MOCK ? mockDelay({ ok: true }) : apiPost(`/vault/refs/${input.id}/rotate`, { secret: input.secret }),
      onSuccess: invalidate,
    }),
  };
}

export function useMcpKeys() {
  return useQuery({
    queryKey: ["mcp-keys"],
    queryFn: async () => (USE_MOCK ? mockDelay([] as McpKey[]) : apiGet<McpKey[]>("/mcp/keys")),
    staleTime: 15_000,
  });
}

export function useMcpKeyMutations() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["mcp-keys"] });
  return {
    mint: useMutation({
      mutationFn: (payload: { name: string; scopes: string[] }) =>
        USE_MOCK
          ? mockDelay({
              id: "mcpk-mock",
              name: payload.name,
              prefix: "mcp_moc",
              scopes: payload.scopes,
              revoked: false,
              key: "mcp_mock-shown-once",
            } satisfies McpKey)
          : apiPost<McpKey>("/mcp/keys", payload),
      onSuccess: invalidate,
    }),
    rotate: useMutation({
      mutationFn: (id: string) =>
        USE_MOCK ? mockDelay({ key: "mcp_rotated-shown-once" }) : apiPost<McpKey>(`/mcp/keys/${id}/rotate`, {}),
      onSuccess: invalidate,
    }),
    revoke: useMutation({
      mutationFn: (id: string) =>
        USE_MOCK ? mockDelay({ ok: true }) : apiPost(`/mcp/keys/${id}/revoke`, {}),
      onSuccess: invalidate,
    }),
  };
}

export function useMcpStatus() {
  return useQuery({
    queryKey: ["mcp-status"],
    queryFn: async () => (USE_MOCK ? mockDelay(MOCK_MCP_STATUS) : apiGet<McpStatus>("/mcp/status")),
    staleTime: 30_000,
  });
}

export function useMcpTasks() {
  return useQuery({
    queryKey: ["mcp-tasks"],
    queryFn: async () => (USE_MOCK ? mockDelay([] as McpTask[]) : apiGet<McpTask[]>("/mcp/tasks")),
    staleTime: 10_000,
  });
}

export function useGatewayStatus() {
  return useQuery({
    queryKey: ["gateway-status"],
    queryFn: async () => (USE_MOCK ? mockDelay(MOCK_GATEWAY) : apiGet<GatewayStatus>("/gateway/status")),
    staleTime: 30_000,
  });
}

export function useGatewayCanary() {
  return useQuery({
    queryKey: ["gateway-canary"],
    queryFn: async () =>
      USE_MOCK
        ? mockDelay({ current: null, history: [] as GatewayCanary[] })
        : apiGet<{ current: GatewayCanary | null; history: GatewayCanary[] }>("/gateway/canary"),
    staleTime: 15_000,
  });
}

export function useProposeGatewayCanary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (candidateModel: string) => apiPost<GatewayCanary>("/gateway/canary", { candidateModel }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["gateway-canary"] });
      void qc.invalidateQueries({ queryKey: ["gateway-status"] });
    },
  });
}

export function usePromoteGatewayCanary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<GatewayCanary>(`/gateway/canary/${id}/promote`, {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["gateway-canary"] });
      void qc.invalidateQueries({ queryKey: ["gateway-status"] });
    },
  });
}

export function useA2aPartners() {
  return useQuery({
    queryKey: ["a2a-partners"],
    queryFn: async () => (USE_MOCK ? mockDelay([] as A2aPartner[]) : apiGet<A2aPartner[]>("/a2a/partners")),
    staleTime: 15_000,
  });
}

export function useA2aTasks() {
  return useQuery({
    queryKey: ["a2a-tasks"],
    queryFn: async () => (USE_MOCK ? mockDelay([] as A2aTask[]) : apiGet<A2aTask[]>("/a2a/tasks")),
    staleTime: 10_000,
  });
}

export function useUpsertA2aPartner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; certDn: string; cardUrl?: string; allowedSkills?: string[] }) =>
      apiPost<A2aPartner>("/a2a/partners", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["a2a-partners"] }),
  });
}
