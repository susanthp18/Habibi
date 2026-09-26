/**
 * `@/lib/signalingUrl` for the ported screens: a test call's signalling socket
 * goes through the gateway, authorised by a one-use ticket for this exact path
 * (a browser cannot put the session's credentials on a WebSocket).
 */
import { studioSocketUrl } from "@/api/studio-engine";

export function signalingUrl(
  workflowId: number | string,
  workflowRunId: number | string,
  _accessToken: string | null,
): Promise<string> {
  return studioSocketUrl(`/api/v1/ws/signaling/${workflowId}/${workflowRunId}`);
}
