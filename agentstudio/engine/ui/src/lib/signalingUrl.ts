import { client } from "@/client/client.gen";
import { resolveBrowserBackendUrl } from "@/lib/apiClient";

/**
 * WebSocket URL for a test call's WebRTC signalling.
 *
 * Async so a host that embeds this UI behind its own gateway can mint a
 * per-socket credential first (the AgentStudio port replaces this module).
 */
export async function signalingUrl(
    workflowId: number | string,
    workflowRunId: number | string,
    accessToken: string | null,
): Promise<string> {
    const baseUrl = client.getConfig().baseUrl || resolveBrowserBackendUrl();
    const wsUrl = baseUrl.replace(/^http/, "ws");
    return `${wsUrl}/api/v1/ws/signaling/${workflowId}/${workflowRunId}?token=${accessToken}`;
}
