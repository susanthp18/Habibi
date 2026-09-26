import { apiDelete, apiGet, apiPost, API_BASE_URL } from "./config";

export const STUDIO_MCP_URL = `${API_BASE_URL}/studio-mcp/`;

export type StudioMcpKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expiresAt: string;
  createdAt: string;
  lastUsedAt: string | null;
  revoked: boolean;
};

export type CreatedStudioMcpKey = StudioMcpKey & { key: string };

export function listStudioMcpKeys() {
  return apiGet<StudioMcpKey[]>("/voice-studio/mcp-keys");
}

export function createStudioMcpKey(name: string, scopes: string[], expiresInDays: number) {
  return apiPost<CreatedStudioMcpKey>("/voice-studio/mcp-keys", { name, scopes, expiresInDays });
}

export function rotateStudioMcpKey(id: string) {
  return apiPost<CreatedStudioMcpKey>(
    `/voice-studio/mcp-keys/${encodeURIComponent(id)}/rotate`,
    {},
  );
}

export function revokeStudioMcpKey(id: string) {
  return apiDelete(`/voice-studio/mcp-keys/${encodeURIComponent(id)}`);
}
