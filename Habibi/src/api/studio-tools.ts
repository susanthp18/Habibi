import { apiGet, apiPost } from "./config";

export type StudioToolRevision = {
  revision: number;
  digest: string;
  state: "draft" | "submitted" | "approved" | "rejected" | "revoked" | "legacy";
  snapshot: { name: string; category: string; definition: Record<string, unknown> };
  policy: Record<string, unknown>;
  authoredBy: number;
  reviewedBy: number | null;
  createdAt: string;
  publishedUsage: number;
};

export type StudioToolPolicy = {
  risk: "read" | "write" | "platform";
  channels: Array<"inbound" | "outbound" | "whatsapp">;
  min_identity: "none" | "endpoint" | "challenge";
  egress_fields: string[];
  success_path: string;
  success_value: unknown;
  error_code_path?: string;
  idempotency_parameter?: string;
  allowed_mcp_functions: Record<string, string>;
  result_schema: Record<string, unknown>;
};

const path = (uuid: string) => `/studio-api/api/v1/tools/${encodeURIComponent(uuid)}/revisions`;

export function listStudioToolRevisions(uuid: string) {
  return apiGet<StudioToolRevision[]>(path(uuid));
}

export function submitStudioToolRevision(uuid: string, revision: number, policy: StudioToolPolicy) {
  return apiPost<{ state: string; digest: string }>(`${path(uuid)}/${revision}/submit`, policy);
}

export function reviewStudioToolRevision(
  uuid: string,
  revision: number,
  decision: "approved" | "rejected" | "revoked",
) {
  return apiPost<{ state: string; digest: string }>(
    `/voice-studio/tools/${encodeURIComponent(uuid)}/revisions/${revision}/review`,
    { decision },
  );
}
