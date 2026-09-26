// -----------------------------------------------------------------------------
// AgentStudio engine: where its API is and how its requests are signed.
//
// The engine is reached only through our backend's gateway (/studio-api),
// which checks the caller's permissions and forwards their identity. The
// ported AgentStudio screens (src/agentstudio) use the engine's generated
// client; this module points that client at the gateway and signs every
// request with the same credentials as the rest of the app.
// -----------------------------------------------------------------------------

import { API_BASE_URL, apiPost, authHeaders } from "./config";

/** Base URL the generated engine client prefixes its `/api/v1/...` paths with. */
export const STUDIO_API_BASE = `${API_BASE_URL}/studio-api`;

/** The app's credentials (Entra bearer, or API key + actor in local dev). */
export function studioAuthHeaders(): Promise<Headers> {
  return authHeaders();
}

/**
 * A WebSocket URL for an engine socket path (e.g. `/api/v1/ws/signaling/1/2`).
 *
 * Browsers cannot put headers on a socket, so the gateway issues a one-use,
 * short-lived ticket for this exact path; the ticket is the credential.
 */
export async function studioSocketUrl(enginePath: string, query = ""): Promise<string> {
  const { ticket } = await apiPost<{ ticket: string }>("/studio-api/_ws-ticket", {
    path: enginePath,
  });
  const origin = API_BASE_URL.replace(/^http/, "ws");
  const path = enginePath.startsWith("/") ? enginePath : `/${enginePath}`;
  return `${origin}/studio-ws/${encodeURIComponent(ticket)}${path}${query ? `?${query}` : ""}`;
}
