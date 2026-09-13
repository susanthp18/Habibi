/**
 * Skills: the signed packs a card attaches. Carved out of api/agent-studio,
 * which keeps the cards, the compiler and the change log.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiDelete,
  apiGet,
  apiGetBlob,
  apiPatch,
  apiPost,
  apiUpload,
  retryUnlessClientError,
} from "./config";
import { invalidateAgentStudio } from "./agent-studio";

/** Mirrors `AgentStudioSkillVersionResponse`. */
export type SkillVersion = {
  id: string;
  skillId: string;
  version: string;
  status: string;
  frontmatter: Record<string, unknown>;
  body: string;
  allowedTools: string[];
  contentHash: string;
  signature: string | null;
  signedBy: string | null;
  pack: Record<string, unknown>;
  description: string;
  evalSuite: unknown | null;
  origin: unknown | null;
};

/** Library row. Mirrors `AgentStudioSkillSummaryResponse`. */
export type SkillSummary = {
  id: string;
  slug: string;
  origin: string;
  signatureStatus: string;
  latestVersionId?: string | null;
  description: string;
  allowedTools: string[];
  version: string;
  status: string;
  attachedCards: string[];
  /** `attachedCards` plus draft versions — which card can rehearse this skill. */
  rehearsalCards?: string[];
  /** Lint findings the save returned (a create or import); the author is told. */
  lintWarnings?: Record<string, unknown>[] | null;
  evalSuite?: unknown | null;
  contentHash?: string;
  signed: boolean;
  hasSignedVersion?: boolean;
  bodyTokens?: number;
  referenceFiles?: string[];
};

/** `get_skill`'s detail. Mirrors `AgentStudioSkillResponse`. */
export type SkillDetail = SkillSummary & {
  versions?: SkillVersion[] | null;
  frontmatter?: Record<string, unknown> | null;
  body?: string | null;
  pack?: { references?: Record<string, string> } | null;
  markdown?: string | null;
};

export function useAgentStudioSkills() {
  return useQuery({
    queryKey: ["agent-studio", "skills"],
    queryFn: async () => apiGet<SkillSummary[]>("/agent-studio/skills"),
  });
}

export function useAgentStudioSkill(skillId: string) {
  return useQuery({
    queryKey: ["agent-studio", "skill", skillId],
    queryFn: async (): Promise<SkillDetail | null> =>
      apiGet<SkillDetail>(`/agent-studio/skills/${skillId}`),
    enabled: Boolean(skillId),
    // A 404 is the server's final answer about this id. RQ's default of three
    // tries turned a mistyped URL into roughly seven seconds of spinner before
    // the page was allowed to say so.
    retry: retryUnlessClientError,
  });
}

export function useCreateSkill() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: {
      slug: string;
      description?: string;
      allowedTools?: string[];
      body?: string;
    }) => apiPost<SkillSummary>("/agent-studio/skills", body),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (skillId: string) =>
      apiDelete<{ ok: boolean; id: string; slug: string }>(`/agent-studio/skills/${skillId}`),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function useSkillScripts() {
  return useQuery({
    queryKey: ["agent-studio", "skill-scripts"],
    queryFn: async () => apiGet<{ name: string }[]>("/agent-studio/skills/scripts"),
    staleTime: 5 * 60_000,
  });
}

export function useSignSkill() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (skillId: string) => apiPost(`/agent-studio/skills/${skillId}/sign`, {}),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function useRevertSkill() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { skillId: string; versionId?: string }) =>
      apiPost(`/agent-studio/skills/${body.skillId}/revert`, { versionId: body.versionId }),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function usePatchSkill(skillId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: Record<string, unknown>) =>
      apiPatch(`/agent-studio/skills/${skillId}`, body),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}

export function useRunSkillScript() {
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { name: string; payload: Record<string, unknown> }) =>
      apiPost<{ ok: boolean; error?: string } & Record<string, unknown>>(
        "/agent-studio/skills/run-script",
        body,
      ),
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
  // Revoking in the same tick can abort the download in Chromium. Give the
  // navigation a moment, then release the object URL.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function importSkillZip(file: File): Promise<SkillSummary> {
  const form = new FormData();
  form.append("file", file);
  // The route reads at most 2 MB and only a .zip or a bare SKILL.md.
  return apiUpload<SkillSummary>("/agent-studio/skills/import", form, {
    maxBytes: 2_000_000,
    accept: [".zip", ".md"],
  });
}

export function useCloneSkill() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { skillId: string; slug: string }) =>
      apiPost(`/agent-studio/skills/${body.skillId}/clone`, { slug: body.slug }),
    onSuccess: () => invalidateAgentStudio(qc),
  });
}
