/**
 * `@/lib/apiClient` for the ported AgentStudio screens: the engine's generated
 * client talks to our gateway, never to the engine directly, and every request
 * carries the app's own credentials (whatever a screen set is replaced).
 */
import { STUDIO_API_BASE, studioAuthHeaders } from "@/api/studio-engine";
import type { Client } from "@/agentstudio/client/client";
import type { CreateClientConfig } from "@/agentstudio/client/client.gen";

export function getServerBackendUrl(): string {
  return STUDIO_API_BASE;
}

export function resolveBrowserBackendUrl(_backendApiEndpoint?: string | null): string {
  return STUDIO_API_BASE;
}

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: STUDIO_API_BASE,
});

const signed = new WeakSet<Client>();

/** Sign every request on `apiClient` with the app's credentials. Idempotent. */
export function signStudioClient(apiClient: Client): void {
  if (signed.has(apiClient)) return;
  signed.add(apiClient);
  apiClient.interceptors.request.use(async (request) => {
    const auth = await studioAuthHeaders();
    request.headers.delete("Authorization");
    request.headers.delete("X-API-Key");
    auth.forEach((value, key) => {
      if (key.toLowerCase() !== "accept") request.headers.set(key, value);
    });
    return request;
  });
}

/** Kept for the screens that call it; signing is global (see signStudioClient). */
export function setupAuthInterceptor(
  apiClient: Client,
  _getAccessToken?: () => Promise<string>,
): void {
  signStudioClient(apiClient);
}
