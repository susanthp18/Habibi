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
